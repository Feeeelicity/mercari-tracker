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

def get_live_exchange_rate():
    try:
        res = requests.get("https://open.er-api.com/v6/latest/JPY", timeout=8)
        if res.status_code == 200:
            data = res.json()
            rate = data.get("rates", {}).get("HKD")
            if rate:
                return float(rate)
    except Exception as e:
        print(f"主要匯率 API 連線異常: {e}")

    try:
        res = requests.get("https://api.frankfurter.app/latest?from=JPY&to=HKD", timeout=8)
        if res.status_code == 200:
            data = res.json()
            rate = data.get("rates", {}).get("HKD")
            if rate:
                return float(rate)
    except Exception as e:
        print(f"備用匯率 API 連線異常: {e}")

    return 0.051

def format_dual_price(yen_amount, rate):
    hkd_val = round(yen_amount * rate, 1)
    return f"¥{yen_amount:,}（約 HK${hkd_val:,.1f}，匯率 {rate:.4f}）"

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

def fetch_item_info(page, hk_url):
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
    except Exception:
        pass

    yen_price = None
    try:
        raw_body = page.inner_text("body")
        yen_match = re.search(r"\(JP[¥￥]([0-9,]+)\)|\([¥￥]([0-9,]+)\)|JP[¥￥]\s*([0-9,]+)", raw_body)
        if yen_match:
            yen_str = yen_match.group(1) or yen_match.group(2) or yen_match.group(3)
            yen_price = int(yen_str.replace(",", ""))
    except Exception as e:
        print(f"解析日圓原價出錯: {e}")

    return title, yen_price

def check_all():
    items = load_items()
    if not items:
        print("未在 items.txt 找到任何商品！")
        return

    live_rate = get_live_exchange_rate()
    print(f"📊 當刻最新日圓兌港幣市場即時匯率: {live_rate:.5f}")

    history = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
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
            jp_url = item["jp_url"]
            hk_url = item["hk_url"]
            
            web_title, yen_price = fetch_item_info(page, hk_url)
            display_name = name if name != item_id else (web_title or item_id)

            if not yen_price:
                print(f"❌ 無法讀取 [{display_name}] 價格")
                continue

            current_fmt = format_dual_price(yen_price, live_rate)
            print(f"[{display_name}] 當前價: {current_fmt}")
            
            old_yen = history.get(item_id)

            if old_yen is None:
                msg = (
                    f"🟢 <b>Mercari 雲端監控已加入！</b>\n"
                    f"商品：{display_name}\n"
                    f"目前價格：<b>{current_fmt}</b>\n"
                    f"🔗 <a href=\"{hk_url}\">香港頁面</a> | <a href=\"{jp_url}\">日本原站</a>\n"
                    f"<code>{jp_url}</code>（點擊可直接複製）"
                )
                send_telegram_alert(msg)
            elif yen_price != old_yen:
                old_fmt = format_dual_price(old_yen, live_rate)
                diff = yen_price - old_yen
                diff_fmt = format_dual_price(abs(diff), live_rate)
                
                if diff < 0:
                    status = f"🚨 <b>價格下跌！快搶！</b> (日圓降了 {diff_fmt})"
                else:
                    status = f"📈 <b>價格上漲！</b> (日圓升了 {diff_fmt})"

                msg = (
                    f"{status}\n"
                    f"商品：{display_name}\n"
                    f"價格變動：{old_fmt} ➔ <b>{current_fmt}</b>\n"
                    f"🔗 <a href=\"{hk_url}\">香港頁面</a> | <a href=\"{jp_url}\">日本原站</a>\n"
                    f"<code>{jp_url}</code>（點擊可直接複製）"
                )
                send_telegram_alert(msg)

            history[item_id] = yen_price

        browser.close()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    print("🚀 啟動多商品實時外匯雙幣監控...")
    for i in range(300):
        try:
            check_all()
        except Exception as e:
            print(f"輪巡出錯: {e}")
        time.sleep(30)
