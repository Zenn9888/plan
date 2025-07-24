import re
import requests
import googlemaps
from urllib.parse import unquote
import os
from dotenv import load_dotenv

# ✅ 載入 API 金鑰（記得先建立 .env 檔案並設定 GOOGLE_MAPS_API_KEY）
load_dotenv()
GOOGLE_API_KEY = "AIzaSyC23VZqlnI8HYAgMA6C_2a0u1umq8UOfvs"
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

def resolve_place_name(input_text):
    try:
        print(f"📥 嘗試解析：{input_text}")

        if input_text.startswith("http"):
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            url = res.url
            print(f"🔁 重定向後 URL: {url}")
        else:
            url = input_text

        # 1️⃣ /place/ 直接擷取名稱
        place_match = re.search(r"/place/([^/]+)", url)
        if place_match:
            name = unquote(place_match.group(1))
            print(f"🏷️ 擷取 /place/: {name}")
            return name

        # 2️⃣ 如果網址中含有 q=（用 API 查）
        q_match = re.search(r"[?&]q=([^&]+)", url)
        if q_match:
            address_text = unquote(q_match.group(1))
            print(f"📌 擷取 ?q=: {address_text}")
            result = gmaps.find_place(address_text, input_type="textquery", fields=["place_id"])
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"])
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 3️⃣ fallback：直接查詢文字
        result = gmaps.find_place(input_text, input_type="textquery", fields=["place_id"])
        if result.get("candidates"):
            place_id = result["candidates"][0]["place_id"]
            details = gmaps.place(place_id=place_id, fields=["name"])
            name = details["result"]["name"]
            print(f"✅ 最終 API 名稱：{name}")
            return name

    except Exception as e:
        print(f"❌ 錯誤：{e}")

    return None

# ✅ 測試用
if __name__ == "__main__":
    # 可替換為其他 Google Maps 短網址
    test_input = "https://maps.app.goo.gl/q3f2TKiwyu5XkcWj6"
    name = resolve_place_name(test_input)
    print("測試結果：", name if name else "⚠️ 無法解析")
