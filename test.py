import re
import requests
import googlemaps
from urllib.parse import unquote
from dotenv import load_dotenv
import os

# 讀取 Google Maps API Key
load_dotenv()
GOOGLE_API_KEY = "AIzaSyC23VZqlnI8HYAgMA6C_2a0u1umq8UOfvs"

gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

def resolve_place_name(input_text):
    try:
        print(f"📥 嘗試解析：{input_text}")

        if input_text.startswith("http"):
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(input_text, headers=headers, allow_redirects=True, timeout=10)
            url = res.url
            print(f"🔁 重定向後 URL: {url}")
        else:
            url = input_text

        # 1️⃣ /place/ 擷取 + Google API 查詢
        place_match = re.search(r"/place/([^/]+)", url)
        if place_match:
            keyword = unquote(place_match.group(1))
            print(f"🏷️ 擷取 /place/: {keyword}")
            result = gmaps.find_place(keyword, input_type="textquery", fields=["place_id"], language="zh-TW")
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 2️⃣ 查詢參數 q
        q_match = re.search(r"[?&]q=([^&]+)", url)
        if q_match:
            keyword = unquote(q_match.group(1))
            print(f"📌 擷取 ?q=: {keyword}")
            result = gmaps.find_place(keyword, input_type="textquery", fields=["place_id"], language="zh-TW")
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 3️⃣ fallback：直接查詢原始內容
        result = gmaps.find_place(input_text, input_type="textquery", fields=["place_id"], language="zh-TW")
        if result.get("candidates"):
            place_id = result["candidates"][0]["place_id"]
            details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
            name = details["result"]["name"]
            print(f"✅ fallback API 名稱：{name}")
            return name

    except Exception as e:
        print(f"❌ 錯誤：{e}")
    return None

# 測試短網址
print("測試結果：", resolve_place_name("https://maps.app.goo.gl/wmUbv4taYMZ8Zz3V8"))
