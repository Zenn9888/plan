import os
import re
import requests
import googlemaps
import hmac
import hashlib
import base64
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
from urllib.parse import unquote

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi,
    MessagingApiBlob,
    Configuration,
    ApiClient,
    ReplyMessageRequest,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging.models import TextMessage

# === ✅ 載入環境變數 ===
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# === ✅ 初始化服務 ===
app = Flask(__name__)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["line_bot_db"]
collection = db["locations"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
api_instance = MessagingApi(ApiClient(configuration))
blob_api = MessagingApiBlob(ApiClient(configuration))

# === ✅ 指令集別名與正則 ===
ADD_ALIASES = ["新增", "加入", "增加", "+", "加", "增"]
DELETE_PATTERN = ["刪除", "移除", "del", "delete", "-", "刪", "移"]
COMMENT_PATTERN = ["註解", "備註", "note", "comment", "註", "*"]

def verify_signature(secret, body, signature):
    hash = hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest()
    computed_signature = base64.b64encode(hash).decode('utf-8')
    return hmac.compare_digest(computed_signature, signature)

# === ✅ 解析 Google Maps 短網址成地名（繁體中文 + 地點名稱） ===
def resolve_place_name(input_text):
    try:
        print(f"📥 嘗試解析：{input_text}")

        if input_text.startswith("http"):
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            url = res.url
            print(f"🔁 重定向後 URL: {url}")
        else:
            url = input_text

        # 1️⃣ 如果網址中有 /place/，直接擷取地名
        place_match = re.search(r"/place/([^/]+)", url)
        if place_match:
            name = unquote(place_match.group(1))
            print(f"🏷️ 擷取 /place/: {name}")
            # 再透過 API 查詢正規名稱
            result = gmaps.find_place(name, input_type="textquery", fields=["place_id"], language="zh-TW")
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 2️⃣ 如果網址中有 q=，不要直接用，改用 q 的值去查 API 取得地點名稱
        q_match = re.search(r"[?&]q=([^&]+)", url)
        if q_match:
            address_text = unquote(q_match.group(1))
            print(f"📌 擷取 ?q=: {address_text}")
            result = gmaps.find_place(address_text, input_type="textquery", fields=["place_id"], language="zh-TW")
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 3️⃣ 最後 fallback：直接查輸入值
        result = gmaps.find_place(input_text, input_type="textquery", fields=["place_id"], language="zh-TW")
        if result.get("candidates"):
            place_id = result["candidates"][0]["place_id"]
            details = gmaps.place(place_id=place_id, fields=["name"], language="zh-TW")
            name = details["result"]["name"]
            print(f"✅ 最終 API 名稱：{name}")
            return name

    except Exception as e:
        print(f"❌ 錯誤：{e}")
    return None
