"""
Instagram Parser Server (без браузера)
=======================================
Работает на бесплатном Render через HTTP-запросы с куками.
"""

import re
import time
import random
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

COOKIES_FILE = "cookies.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.instagram.com/",
    "X-IG-App-ID": "936619743392459",
}


def load_cookies():
    """Загружает куки из файла и возвращает dict для requests."""
    if not os.path.exists(COOKIES_FILE):
        return {}
    with open(COOKIES_FILE, "r") as f:
        data = json.load(f)
    cookie_list = data if isinstance(data, list) else data.get("cookies", [])
    return {c["name"]: c["value"] for c in cookie_list if "name" in c and "value" in c}


def parse_number(s):
    s = re.sub(r"[^\dKkMmBb\.]", "", str(s)).strip().upper()
    mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, m in mult.items():
        if s.endswith(suffix):
            try:
                return int(float(s[:-1]) * m)
            except ValueError:
                return 0
    try:
        return int(s)
    except ValueError:
        return 0


def extract_articles(caption):
    matches = re.findall(r"#(\d+|ww\S*)", caption, flags=re.IGNORECASE)
    return [f"#{m.upper()}" for m in matches]


def get_profile_posts(username, cookies, session):
    """Получает список постов профиля через Instagram API."""
    posts = []

    # Получаем user_id через API
    try:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        resp = session.get(url, headers=HEADERS, cookies=cookies, timeout=15)
        if resp.status_code != 200:
            print(f"Ошибка получения профиля @{username}: {resp.status_code}")
            return []

        data = resp.json()
        user = data.get("data", {}).get("user", {})
        user_id = user.get("id")
        if not user_id:
            print(f"Не найден user_id для @{username}")
            return []

        print(f"@{username} → user_id: {user_id}")

    except Exception as e:
        print(f"Ошибка профиля @{username}: {e}")
        return []

    # Получаем посты через GraphQL
    end_cursor = None
    page = 0

    while True:
        page += 1
        try:
            variables = json.dumps({
                "id": user_id,
                "first": 50,
                "after": end_cursor,
            })

            url = (
                "https://www.instagram.com/graphql/query/"
                "?query_hash=e769aa130647d2354c40ea6a439bfc08"
                f"&variables={requests.utils.quote(variables)}"
            )

            resp = session.get(url, headers=HEADERS, cookies=cookies, timeout=15)
            if resp.status_code != 200:
                print(f"Ошибка GraphQL стр.{page}: {resp.status_code}")
                break

            data = resp.json()
            media = (
                data.get("data", {})
                    .get("user", {})
                    .get("edge_owner_to_timeline_media", {})
            )

            edges = media.get("edges", [])
            if not edges:
                break

            for edge in edges:
                node = edge.get("node", {})
                shortcode = node.get("shortcode")
                if not shortcode:
                    continue

                # Дата
                timestamp = node.get("taken_at_timestamp")
                post_date = datetime.fromtimestamp(timestamp) if timestamp else None

                # Описание
                caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                caption = caption_edges[0]["node"]["text"] if caption_edges else ""

                # Просмотры (только для видео)
                views = node.get("video_view_count", 0) or 0

                # Лайки
                likes = node.get("edge_liked_by", {}).get("count", 0) or 0

                # Тип
                is_video = node.get("is_video", False)

                posts.append({
                    "url":      f"https://www.instagram.com/p/{shortcode}/",
                    "caption":  caption,
                    "views":    views,
                    "likes":    likes,
                    "date":     post_date,
                    "is_video": is_video,
                })

            # Пагинация
            page_info = media.get("page_info", {})
            if not page_info.get("has_next_page"):
                break

            end_cursor = page_info.get("end_cursor")
            time.sleep(random.uniform(1.5, 3))

        except Exception as e:
            print(f"Ошибка GraphQL стр.{page}: {e}")
            break

    print(f"@{username}: получено постов — {len(posts)}")
    return posts


def run_parse(accounts, date_from, date_to, mode="articles"):
    cookies = load_cookies()
    session = requests.Session()
    results = []

    for account in accounts:
        print(f"\nОбрабатываем @{account}...")
        posts = get_profile_posts(account, cookies, session)

        for post in posts:
            post_date = post["date"]

            # Фильтр по дате
            if post_date and not (date_from <= post_date <= date_to):
                continue

            if mode == "articles":
                articles = extract_articles(post["caption"])
                if not articles:
                    continue
                for art in articles:
                    results.append({
                        "account":  f"@{account}",
                        "article":  art,
                        "date":     post_date.strftime("%d.%m.%Y") if post_date else "—",
                        "views":    post["views"],
                        "likes":    post["likes"],
                        "url":      post["url"],
                        "caption":  post["caption"][:150].replace("\n", " "),
                    })
            else:
                results.append({
                    "account":  f"@{account}",
                    "date":     post_date.strftime("%d.%m.%Y") if post_date else "—",
                    "views":    post["views"],
                    "likes":    post["likes"],
                    "articles": ", ".join(extract_articles(post["caption"])) or "—",
                    "url":      post["url"],
                    "caption":  post["caption"][:150].replace("\n", " "),
                })

    return results


# ─────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "Сервер работает"})


@app.route("/parse", methods=["POST"])
def parse():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных в запросе"}), 400

        accounts     = data.get("accounts", [])
        date_from_s  = data.get("date_from", "")
        date_to_s    = data.get("date_to", "")
        mode         = data.get("mode", "articles")

        if not accounts:
            return jsonify({"error": "Не указаны аккаунты"}), 400
        if not date_from_s or not date_to_s:
            return jsonify({"error": "Не указан период"}), 400

        try:
            date_from = datetime.strptime(date_from_s, "%d.%m.%Y")
            date_to   = datetime.strptime(date_to_s,   "%d.%m.%Y")
        except ValueError:
            return jsonify({"error": "Неверный формат даты. Используйте ДД.ММ.ГГГГ"}), 400

        print(f"Запрос: {accounts}, {date_from_s}–{date_to_s}, режим={mode}")
        results = run_parse(accounts, date_from, date_to, mode)

        return jsonify({"status": "ok", "count": len(results), "results": results})

    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
