import os
import re
import requests
import logging
import googlemaps
from urllib.parse import urlparse, parse_qs, unquote
from dotenv import load_dotenv

# ✅ 載入 .env
load_dotenv()
GOOGLE_API_KEY ="AIzaSyC23VZqlnI8HYAgMA6C_2a0u1umq8UOfvs"
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

# ✅ 初始化 logger
logging.basicConfig(level=logging.INFO)

# ✅ 中文正則表達式
CHINESE_NAME_PATTERN = r'[\u4e00-\u9fff]{2,}'

# ✅ 清理地點標題：擷取主要名稱（丟掉 + 推薦字串）
def clean_place_title(name):
    # ✅ 將 + 號轉空格
    name = name.replace("+", " ")
    for delimiter in ['｜', '|', '-', '、', '(', '（']:
        name = name.split(delimiter)[0]
    cleaned = name.strip()
    logging.info(f"✨ 清理後名稱：{cleaned}")
    return cleaned

# ✅ 優先從 ?q= 地址擷取地標名稱
def extract_chinese_name_from_q(q):
    chinese_matches = re.findall(CHINESE_NAME_PATTERN, q)
    if chinese_matches:
        name = chinese_matches[-1]
        logging.info(f"🏷️ 擷取地標名稱：{name}")
        return name
    logging.warning(f"⚠️ 找不到中文地名，fallback 使用原始 q 值：{q}")
    return q

# ✅ 主函式：輸入網址或地名 → 回傳簡化後名稱
def resolve_place_name(user_input):
    try:
        if "maps.app.goo.gl" in user_input:
            logging.info(f"📥 嘗試解析：{user_input}")
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(user_input, headers=headers, allow_redirects=True, timeout=5)
            redirect_url = resp.url
            logging.info(f"🔁 重定向後 URL: {redirect_url}")

            parsed_url = urlparse(redirect_url)

            # ✅ 處理 /place/
            if "/place/" in parsed_url.path:
                parts = parsed_url.path.split("/place/")
                if len(parts) > 1:
                    name_part = parts[1].split("/")[0]
                    name = unquote(name_part)
                    if re.search(CHINESE_NAME_PATTERN, name):
                        cleaned = clean_place_title(name)
                        logging.info(f"🏷️ 擷取地標名稱（/place/）：{cleaned}")
                        return cleaned

            # ✅ 處理 ?q=
            query = parse_qs(parsed_url.query)
            if "q" in query:
                raw_q = query["q"][0]
                raw_q = unquote(raw_q)
                logging.info(f"📌 擷取 ?q=: {raw_q}")
                place_name = extract_chinese_name_from_q(raw_q)
                if place_name:
                    return place_name
                logging.warning(f"⚠️ regex 擷取失敗，嘗試用 Google API 查詢：{raw_q}")
                result = gmaps.find_place(input=raw_q, input_type="textquery", fields=["name"])
                candidates = result.get("candidates")
                if candidates:
                    name = candidates[0].get("name")
                    logging.info(f"📍 API 擷取地點：{name}")
                    return name
                else:
                    logging.warning(f"❌ API 找不到地點：{raw_q}")

        # ✅ 非短網址：直接查詢 API
        logging.info(f"🔍 非 maps.app.goo.gl 網址，直接查詢：{user_input}")
        result = gmaps.find_place(input=user_input, input_type="textquery", fields=["name"])
        candidates = result.get("candidates")
        if candidates:
            name = candidates[0].get("name")
            logging.info(f"📍 API 直接查詢結果：{name}")
            return name
        else:
            logging.warning(f"❌ API 查無結果：{user_input}")

    except Exception as e:
        logging.warning(f"❌ 最終 fallback 查詢失敗：{user_input}\n{e}")

    return "⚠️ 無法解析"

# ✅ 測試
if __name__ == "__main__":
    test_url = "https://maps.app.goo.gl/gtzRjywdwEXhio437"
    result = resolve_place_name(test_url)
    print("測試結果：", result)
