import os
import re
import json
import time
import requests
from playwright.sync_api import sync_playwright

ITEM_ID = "m94085182715"
HK_MERCARI_URL = "https://hk.mercari.com/zh-hant/items/db7dc988-040d-43a6-9421-718d51613ff3"
JP_ORIGINAL_URL = f"https://jp.mercari.com/item/{ITEM_ID}"
DATA_FILE = "price_history.json"
BARK_KEY = "u5QavuFqXT4ps7FxX6vFiS"

def send_bark_alert(title, old_price, new_price, is_test=False):
    if is_test:
        alert_title = "GitHub 雲端監控啟動！"
        body = f"商品：{title}\n目前日圓原價：¥{new_price:,}\n已自動複製連結，打開樂淘一番即可代購！"
    else:
        alert_title = "🚨 Mercari 降價了！快搶！"
        body = f"商品：{title}\n原價 ¥{old_price:,} ➔ 新價 ¥{new_price:,} (降了 ¥{old_price - new_price:,})\n已自動複製連結，打開樂淘一番即可下單！"
    
    api_url = f"https://api.day.app/{BARK_KEY}/"
    payload = {
        "title": alert_title,
        "body": body,
        "url": HK_MERCARI_URL,
        "copy": JP_ORIGINAL_URL,
        "sound": "alarm",
        "group": "Mercari降價提醒"
    }
    try:
        requests.post(api_url, json=payload, timeout=10)
        print("📱 Bark 通知已送出！")
    except Exception as e:
        print(f"發送 Bark 通知出錯: {e}")

def fetch_price():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="zh-HK"
        )
        page = context.new_page()
        page.goto(HK_MERCARI_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        title = "Pretty Rhythm 玩偶"
        try:
            headings = page.locator("h1").all()
            for h in headings:
                txt = h.inner_text().strip()
                if "公告" not in txt and len(txt) > 0:
                    title = txt
                    break
        except:
            pass

        price = None
        try:
            yen_locator = page.locator("text=/\\(JP¥[0-9,]+\\)|\\(¥[0-9,]+\\)/").first
            if yen_locator.count() > 0:
                raw = yen_locator.inner_text()
                match = re.search(r"\(JP[¥￥]([0-9,]+)\)|\([¥￥]([0-9,]+)\)", raw)
                if match:
                    price = int((match.group(1) or match.group(2)).replace(",", ""))
            if not price:
                raw_body = page.inner_text("body")
                match = re.search(r"JP[¥￥]\s*([0-9,]+)", raw_body)
                if match:
                    price = int(match.group(1).replace(",", ""))
        except Exception as e:
            print(f"解析價格出錯: {e}")

        browser.close()
        return title, price

def main():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在執行雲端價格檢查...")
    title, current_price = fetch_price()
    if not current_price:
        print("❌ 未能取得金額。")
        return

    print(f"商品: {title} | 當前日圓價格: ¥{current_price:,}")

    history = {}
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = {}

    old_price = history.get(ITEM_ID)
    if old_price is not None:
        if current_price < old_price:
            print(f"🎉 降價了！從 ¥{old_price:,} 降至 ¥{current_price:,}")
            send_bark_alert(title, old_price, current_price, is_test=False)
        else:
            print("價格無變動。")
    else:
        print("首次在雲端記錄價格，發送測試通知...")
        send_bark_alert(title, current_price, current_price, is_test=True)

    history[ITEM_ID] = current_price
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    # 在雲端持續監控 300 次（每 30 秒一次，約 2.5 小時），降價立刻發 Bark
    for _ in range(300):
        try:
            main()
        except Exception as e:
            print(f"查詢出錯: {e}")
        time.sleep(30)

