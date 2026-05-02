"""
Instagram Parser Server
=======================
Принимает запросы от Google Таблицы, парсит Instagram и возвращает данные.
"""

import re
import time
import random
import json
import os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

COOKIES_FILE = "cookies.json"


def load_cookies():
    if not os.path.exists(COOKIES_FILE):
        return []
    with open(COOKIES_FILE, "r") as f:
        data = json.load(f)
    # Поддерживаем оба формата: список напрямую или {"cookies": [...]}
    if isinstance(data, list):
        return data
    return data.get("cookies", [])


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


def get_caption(page):
    try:
        meta = page.query_selector("meta[property='og:description']")
        if meta:
            content = meta.get_attribute("content") or ""
            if len(content) > 5:
                return content
    except Exception:
        pass
    try:
        for sel in ["article div span", "h1", "ul li span"]:
            for el in page.query_selector_all(sel):
                txt = el.inner_text().strip()
                if len(txt) > 10:
                    return txt
    except Exception:
        pass
    return ""


def get_views(page):
    try:
        for span in page.query_selector_all("span"):
            txt = span.inner_text().strip()
            m = re.search(r"([\d\s,\.]+[KkMmBb]?)\s*(views|просмотр)", txt, re.IGNORECASE)
            if m:
                return parse_number(m.group(1))
    except Exception:
        pass
    try:
        for sel in ["meta[name='description']", "meta[property='og:description']"]:
            meta = page.query_selector(sel)
            if meta:
                content = meta.get_attribute("content") or ""
                m = re.search(r"([\d,\.]+[KkMmBb]?)\s*(views|просмотр)", content, re.IGNORECASE)
                if m:
                    return parse_number(m.group(1))
    except Exception:
        pass
    return 0


def get_date(page):
    try:
        time_el = page.query_selector("time[datetime]")
        if time_el:
            dt_str = time_el.get_attribute("datetime") or ""
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    return None


def get_likes(page):
    try:
        for span in page.query_selector_all("span"):
            txt = span.inner_text().strip()
            m = re.search(r"([\d,]+)\s*(likes|like|отметк)", txt, re.IGNORECASE)
            if m:
                return parse_number(m.group(1))
    except Exception:
        pass
    return 0


def collect_links(page, username, max_scrolls=60):
    try:
        page.goto(f"https://www.instagram.com/{username}/",
                  wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        print(f"Не удалось открыть @{username}: {e}")
        return []

    time.sleep(4)

    if "accounts/login" in page.url:
        print("Сессия истекла — нужно обновить cookies.json")
        return []

    links = set()
    for i in range(max_scrolls):
        for a in page.query_selector_all("a[href*='/p/'], a[href*='/reel/']"):
            href = a.get_attribute("href") or ""
            if href:
                full = "https://www.instagram.com" + href if href.startswith("/") else href
                links.add(full.split("?")[0])

        prev_h = page.evaluate("document.body.scrollHeight")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        if page.evaluate("document.body.scrollHeight") == prev_h:
            break

    return list(links)


def parse_post(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        time.sleep(random.uniform(3, 6))
        try:
            page.wait_for_selector("article", timeout=8000)
        except Exception:
            pass

        if "accounts/login" in page.url:
            return None

        return {
            "url":     url,
            "caption": get_caption(page),
            "views":   get_views(page),
            "date":    get_date(page),
            "likes":   get_likes(page),
        }
    except Exception as e:
        print(f"Ошибка при парсинге {url}: {e}")
        return None


def run_parse(accounts, date_from, date_to, mode="articles"):
    from playwright.sync_api import sync_playwright

    cookies = load_cookies()
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="ru-RU",
        )

        # Загружаем куки
        if cookies:
            ctx.add_cookies(cookies)

        page = ctx.new_page()

        for account in accounts:
            print(f"Обрабатываем @{account}...")
            links = collect_links(page, account)

            for link in links:
                post = parse_post(page, link)
                if not post:
                    continue

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
                            "url":      link,
                            "caption":  post["caption"][:150].replace("\n", " "),
                        })
                else:
                    results.append({
                        "account":  f"@{account}",
                        "date":     post_date.strftime("%d.%m.%Y") if post_date else "—",
                        "views":    post["views"],
                        "likes":    post["likes"],
                        "articles": ", ".join(extract_articles(post["caption"])) or "—",
                        "url":      link,
                        "caption":  post["caption"][:150].replace("\n", " "),
                    })

        browser.close()

    return results


# ──────────────────────────────────────────────────────────────────────────────
# API ENDPOINTS
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Проверка что сервер работает."""
    return jsonify({"status": "ok", "message": "Сервер работает"})


@app.route("/parse", methods=["POST"])
def parse():
    """
    Основной эндпоинт. Принимает JSON:
    {
        "accounts": ["account1", "account2"],
        "date_from": "01.01.2025",
        "date_to": "31.01.2025",
        "mode": "articles"   // или "all"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Нет данных в запросе"}), 400

        accounts = data.get("accounts", [])
        date_from_str = data.get("date_from", "")
        date_to_str = data.get("date_to", "")
        mode = data.get("mode", "articles")

        if not accounts:
            return jsonify({"error": "Не указаны аккаунты"}), 400
        if not date_from_str or not date_to_str:
            return jsonify({"error": "Не указан период"}), 400

        try:
            date_from = datetime.strptime(date_from_str, "%d.%m.%Y")
            date_to   = datetime.strptime(date_to_str,   "%d.%m.%Y")
        except ValueError:
            return jsonify({"error": "Неверный формат даты. Используйте ДД.ММ.ГГГГ"}), 400

        print(f"Запрос: аккаунты={accounts}, период={date_from_str}–{date_to_str}, режим={mode}")

        results = run_parse(accounts, date_from, date_to, mode)

        return jsonify({
            "status":  "ok",
            "count":   len(results),
            "results": results,
        })

    except Exception as e:
        print(f"Ошибка: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
