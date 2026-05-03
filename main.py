"""
Instagram Parser Server v4
===========================
Авторизуется через логин/пароль из переменных окружения.
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

IG_LOGIN    = os.environ.get("IG_LOGIN", "")
IG_PASSWORD = os.environ.get("IG_PASSWORD", "")

SESSION_FILE = "/tmp/ig_session.json"

HEADERS_BROWSER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://www.instagram.com/",
}

HEADERS_API = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-ASBD-ID": "129477",
    "X-IG-WWW-Claim": "0",
    "Origin": "https://www.instagram.com",
    "Referer": "https://www.instagram.com/",
    "Content-Type": "application/x-www-form-urlencoded",
}


def save_session(session):
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump(dict(session.cookies), f)
    except Exception as e:
        print(f"Не удалось сохранить сессию: {e}")


def load_session(session):
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r") as f:
                cookies = json.load(f)
            session.cookies.update(cookies)
            return True
    except Exception:
        pass
    return False


def is_logged_in(session):
    try:
        resp = session.get(
            "https://www.instagram.com/api/v1/accounts/current_user/?edit=true",
            headers=HEADERS_API, timeout=10
        )
        return resp.status_code == 200
    except Exception:
        return False


def login(session):
    """Авторизуется в Instagram и сохраняет сессию."""

    if not IG_LOGIN or not IG_PASSWORD:
        print("ОШИБКА: IG_LOGIN и IG_PASSWORD не заданы в переменных окружения!")
        return False

    print(f"Входим как {IG_LOGIN}...")

    try:
        # Шаг 1 — получаем csrftoken
        resp = session.get(
            "https://www.instagram.com/accounts/login/",
            headers=HEADERS_BROWSER, timeout=15
        )
        csrf = session.cookies.get("csrftoken", "")
        if not csrf:
            match = re.search(r'"csrf_token":"([^"]+)"', resp.text)
            csrf = match.group(1) if match else ""

        print(f"  csrf: {csrf[:10]}...")
        time.sleep(random.uniform(1, 2))

        # Шаг 2 — отправляем логин
        login_headers = {**HEADERS_API, "X-CSRFToken": csrf, "Referer": "https://www.instagram.com/accounts/login/"}
        payload = {
            "username": IG_LOGIN,
            "enc_password": f"#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{IG_PASSWORD}",
            "queryParams": "{}",
            "optIntoOneTap": "false",
        }

        resp = session.post(
            "https://www.instagram.com/api/v1/web/accounts/login/ajax/",
            data=payload,
            headers=login_headers,
            timeout=15,
        )

        print(f"  Статус входа: {resp.status_code}")
        print(f"  Ответ: {resp.text[:200]}")

        data = resp.json()

        if data.get("authenticated"):
            print("✅ Вход выполнен успешно!")
            save_session(session)
            return True
        elif data.get("two_factor_required"):
            print("❌ Требуется двухфакторная аутентификация — отключите её в настройках аккаунта")
            return False
        elif data.get("checkpoint_url"):
            print("❌ Instagram требует подтверждение аккаунта — войдите вручную через браузер")
            return False
        else:
            print(f"❌ Не удалось войти: {data}")
            return False

    except Exception as e:
        print(f"❌ Ошибка при входе: {e}")
        return False


def get_session():
    """Возвращает авторизованную сессию."""
    session = requests.Session()

    # Пробуем загрузить сохранённую сессию
    if load_session(session) and is_logged_in(session):
        print("✅ Сессия активна")
        return session

    # Иначе логинимся заново
    print("Сессия устарела, входим заново...")
    if login(session):
        return session

    return None


def extract_articles(caption):
    matches = re.findall(r"#(\d+|ww\S*)", caption, flags=re.IGNORECASE)
    return [f"#{m.upper()}" for m in matches]


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


def get_user_id(username, session):
    try:
        resp = session.get(
            f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}",
            headers=HEADERS_API, timeout=15
        )
        print(f"  Профиль @{username}: статус {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            user_id = data.get("data", {}).get("user", {}).get("id")
            if user_id:
                return user_id

        # Запасной вариант — через HTML
        resp = session.get(
            f"https://www.instagram.com/{username}/",
            headers=HEADERS_BROWSER, timeout=15
        )
        match = re.search(r'"user_id":"(\d+)"', resp.text)
        if match:
            return match.group(1)

    except Exception as e:
        print(f"  Ошибка получения user_id: {e}")
    return None


def get_posts(username, session):
    posts = []
    user_id = get_user_id(username, session)
    if not user_id:
        print(f"  Не удалось получить user_id для @{username}")
        return []

    print(f"  user_id: {user_id}")
    max_id = None
    page = 0

    while True:
        page += 1
        try:
            params = {"count": 12}
            if max_id:
                params["max_id"] = max_id

            resp = session.get(
                f"https://www.instagram.com/api/v1/feed/user/{user_id}/",
                headers=HEADERS_API, params=params, timeout=15
            )

            print(f"  Страница {page}: статус {resp.status_code}")

            if resp.status_code != 200:
                print(f"  Ответ: {resp.text[:300]}")
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                timestamp  = item.get("taken_at")
                post_date  = datetime.fromtimestamp(timestamp) if timestamp else None
                caption_d  = item.get("caption")
                caption    = caption_d.get("text", "") if caption_d else ""
                views      = item.get("view_count", 0) or item.get("play_count", 0) or 0
                likes      = item.get("like_count", 0) or 0
                code       = item.get("code") or ""
                posts.append({
                    "url":     f"https://www.instagram.com/p/{code}/",
                    "caption": caption,
                    "views":   views,
                    "likes":   likes,
                    "date":    post_date,
                })

            if not data.get("more_available"):
                break
            max_id = data.get("next_max_id")
            if not max_id:
                break

            time.sleep(random.uniform(1.5, 3))

        except Exception as e:
            print(f"  Ошибка стр.{page}: {e}")
            break

    print(f"  Итого постов: {len(posts)}")
    return posts


def run_parse(accounts, date_from, date_to, mode="articles"):
    session = get_session()
    if not session:
        return []

    results = []
    for account in accounts:
        print(f"\n--- @{account} ---")
        posts = get_posts(account, session)

        for post in posts:
            post_date = post["date"]
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
            return jsonify({"error": "Нет данных"}), 400

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
            return jsonify({"error": "Неверный формат даты"}), 400

        results = run_parse(accounts, date_from, date_to, mode)
        return jsonify({"status": "ok", "count": len(results), "results": results})

    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
