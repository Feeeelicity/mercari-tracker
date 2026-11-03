import os
import re
import json
import time
import requests
from playwright.sync_api import sync_playwright

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
ITEMS_FILE = "items.txt"
DATA_FILE = "price_history.json"

def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("未設定 Telegram Token 或 Chat ID")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram 發送失敗: {e}")

def load_items():
    items = []
    if not os.path.exists(ITEMS_FILE):
        return items
    with open(ITEMS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            parts = line.split("#")
            url_part = parts[0].strip()
            name_part = parts[1].strip() if len(parts) > 1 else ""
            
            match = re.search(r"m\d+", url_part)
            if match:
                item_id = match.group(0)
                items.append({
                    "id": item_id,
                    "hk_url": f"https://hk.mercari.com/zh-hant/items/{item_id}",
                    "jp_url": f"https://jp.mercari.com/item/{item_id}",
                    "name": name_part or item_id
                })
    return items

def fetch_price(page, hk_url):
    page.goto(hk_url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(3000)
    
    title = ""
    try:
        headings = page.locator("h1").all()
        for h in headings:
            t = h.inner_text().strip()
            if "公告" not in t and len(t) > 0:
                title = t
                break
    except:
        pass

    price = None
    try:
        yen_locator = page.locator("text=/\\(JP¥[0-9,]+\\)|\\(¥[0-9,]+\\)/").first
        if yen_locator.count() > 0:
            raw = yen_locator.inner_text()
            m = re.search(r"\(JP[¥￥]([0-9,]+)\)|\([¥￥]([0-9,]+)\)", raw)
            if m:
                price = int((m.group(1) or m.group(2)).replace(",", ""))
        if not price:
            raw_body = page.inner_text("body")
            m = re.search(r"JP[¥￥]\s*([0-9,]+)", raw_body)
            if m:
                price = int(m.group(1).replace(",", ""))
    except Exception as e:
        print(f"解析價格出錯: {e}")

    return title, price

def check_all():
    items = load_items()
    if not items:
        print("未在 items.txt 找到任何商品！")
        return

    history = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="zh-HK"
        )
        page = context.new_page()

        for item in items:
            item_id = item["id"]
            name = item["name"]
            web_title, price = fetch_price(page, item["hk_url"])
            display_name = name if name != item_id else (web_title or item_id)

            if not price:
                print(f"❌ 無法讀取 [{display_name}] 價格")
                continue

            print(f"[{display_name}] 當前價: ¥{price:,}")
            old_price = history.get(item_id)

            if old_price is None:
                msg = (
                    f"🟢 <b>Mercari 雲端監控已加入！</b>\n"
                    f"商品：{display_name}\n"
                    f"當前價格：¥{price:,}\n"
                    f"🔗 <a href='{item['hk_url']}'>香港頁面</a> | <a href='{item['jp_url']}'>日本原站</a>\n"
                    f"<code>{item['jp_url']}</code>（點擊可直接複製）"
                )
                send_telegram_alert(msg)
            elif price != old_price:
                diff = price - old_price
                if diff < 0:
                    status = f"🚨 <b>價格下跌！快搶！</b> (降了 ¥{abs(diff):,})"
                else:
                    status = f"📈 <b>價格上漲！</b> (升了 ¥{diff:,})"

                msg = (
                    f"{status}\n"
                    f"商品：{display_name}\n"
                    f"價格：¥{old_price:,} ➔ <b>¥{price:,}</b>\n"
                    f"🔗 <a href='{item['hk_url']}'>香港頁面</a> | <a href='{item['jp_url']}'>日本原站</a>\n"
                    f"<code>{item['jp_url']}</code>（點擊可直接複製）"
                )
                send_telegram_alert(msg)

            history[item_id] = price

        browser.close()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    print("🚀 啟動多商品升降價巡查監控...")
    for i in range(300):
        try:
            check_all()
        except Exception as e:
            print(f"輪巡出錯: {e}")
        time.sleep(30)
