"""
Instagram Parser Server v3
===========================
Использует актуальный Instagram API v1.
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
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-ASBD-ID": "129477",
    "X-IG-WWW-Claim": "0",
    "Origin": "https://www.instagram.com",
    "Referer": "https://www.instagram.com/",
}


def load_cookies():
    if not os.path.exists(COOKIES_FILE):
        print("ВНИМАНИЕ: файл cookies.json не найден!")
        return {}
    with open(COOKIES_FILE, "r") as f:
        data = json.load(f)
    cookie_list = data if isinstance(data, list) else data.get("cookies", [])
    result = {c["name"]: c["value"] for c in cookie_list if "name" in c and "value" in c}
    print(f"Загружено куки: {len(result)} штук")
    return result


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


def get_user_id(username, session, cookies):
    """Получает user_id через страницу профиля."""
    try:
        url = f"https://www.instagram.com/{username}/"
        resp = session.get(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
            "Referer": "https://www.instagram.com/",
        }, cookies=cookies, timeout=15)

        # Ищем user_id в HTML
        match = re.search(r'"user_id":"(\d+)"', resp.text)
        if match:
            return match.group(1)

        match = re.search(r'"id":"(\d+)"', resp.text)
        if match:
            return match.group(1)

        print(f"user_id не найден для @{username}, статус: {resp.status_code}")
        return None

    except Exception as e:
        print(f"Ошибка получения user_id @{username}: {e}")
        return None


def get_posts_via_api(username, session, cookies):
    """Получает посты через Instagram API v1."""
    posts = []

    # Сначала получаем user_id
    user_id = get_user_id(username, session, cookies)
    if not user_id:
        return []

    print(f"@{username} → user_id: {user_id}")

    max_id = None
    page = 0

    while True:
        page += 1
        try:
            url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/"
            params = {"count": 12}
            if max_id:
                params["max_id"] = max_id

            resp = session.get(url, headers=HEADERS, cookies=cookies,
                             params=params, timeout=15)

            print(f"  Страница {page}: статус {resp.status_code}")

            if resp.status_code != 200:
                print(f"  Ответ: {resp.text[:200]}")
                break

            data = resp.json()
            items = data.get("items", [])

            if not items:
                print(f"  Постов больше нет")
                break

            for item in items:
                # Дата
                timestamp = item.get("taken_at")
                post_date = datetime.fromtimestamp(timestamp) if timestamp else None

                # Описание
                caption_data = item.get("caption")
                caption = caption_data.get("text", "") if caption_data else ""

                # Просмотры
                views = item.get("view_count", 0) or item.get("play_count", 0) or 0

                # Лайки
                likes = item.get("like_count", 0) or 0

                # Код поста
                code = item.get("code") or item.get("pk")
                url_post = f"https://www.instagram.com/p/{code}/" if code else ""

                posts.append({
                    "url":     url_post,
                    "caption": caption,
                    "views":   views,
                    "likes":   likes,
                    "date":    post_date,
                })

            # Пагинация
            if not data.get("more_available"):
                print(f"  Достигнут конец ленты")
                break

            max_id = data.get("next_max_id")
            if not max_id:
                break

            time.sleep(random.uniform(1.5, 3))

        except Exception as e:
            print(f"  Ошибка на странице {page}: {e}")
            break

    print(f"@{username}: итого постов — {len(posts)}")
    return posts


def run_parse(accounts, date_from, date_to, mode="articles"):
    cookies = load_cookies()
    session = requests.Session()
    results = []

    for account in accounts:
        print(f"\n--- Обрабатываем @{account} ---")
        posts = get_posts_via_api(account, session, cookies)

        matched = 0
        for post in posts:
            post_date = post["date"]

            if post_date and not (date_from <= post_date <= date_to):
                continue

            if mode == "articles":
                articles = extract_articles(post["caption"])
                if not articles:
                    continue
                for art in articles:
                    matched += 1
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
                matched += 1
                results.append({
                    "account":  f"@{account}",
                    "date":     post_date.strftime("%d.%m.%Y") if post_date else "—",
                    "views":    post["views"],
                    "likes":    post["likes"],
                    "articles": ", ".join(extract_articles(post["caption"])) or "—",
                    "url":      post["url"],
                    "caption":  post["caption"][:150].replace("\n", " "),
                })

        print(f"@{account}: записей добавлено — {matched}")

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

        accounts    = data.get("accounts", [])
        date_from_s = data.get("date_from", "")
        date_to_s   = data.get("date_to", "")
        mode        = data.get("mode", "articles")

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
