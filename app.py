import os
import re
import json
import requests
import googlemaps
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
from urllib.parse import unquote

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage
)
from urllib.parse import unquote
# ✅ 載入 .env 或 Render 環境變數
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# ✅ 初始化 LINE / Maps / Mongo
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

client = MongoClient(MONGO_URL)
db = client["line_bot_db"]
collection = db["locations"]

app = Flask(__name__)

# === 指令別名與正則 ===
ADD_ALIASES = ["新增", "加入", "增加"]
DELETE_PATTERN = r"刪除 (\d+)"
COMMENT_PATTERN = r"註解 (\d+)[\s:：]*(.+)"

# === 解析 Google Maps 網址 / 地點 ===
def resolve_place_name(input_text):
    try:
        print(f"📥 嘗試解析：{input_text}")

        if input_text.startswith("http"):
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            url = res.url
            print(f"🔁 重定向後 URL: {url}")
        else:
            url = input_text

        # 解析 place/ 後的名稱
        place_match = re.search(r"/place/([^/]+)", url)
        if place_match:
            name = unquote(place_match.group(1))
            print(f"🏷️ 抽出地點名稱 /place/: {name}")
            return name

        # 抽出 ?q= 地點參數
        q_match = re.search(r"[?&]q=([^&]+)", url)
        if q_match:
            name = unquote(q_match.group(1))
            print(f"📌 抽出地點名稱 ?q=: {name}")
            return name

        # 最後用 API 查 place_id → 換詳細地址
        result = gmaps.find_place(input_text, input_type="textquery", fields=["place_id"])
        print(f"🔍 API 搜尋結果: {result}")
        if result.get("candidates"):
            place_id = result["candidates"][0]["place_id"]
            details = gmaps.place(place_id=place_id, fields=["formatted_address", "name"])
            name = details["result"].get("formatted_address") or details["result"].get("name")
            print(f"✅ API 解析地點：{name}")
            return name

    except Exception as e:
        print(f"❌ 地點解析錯誤: {e}")
    return None

# === Webhook 路由 ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# === 處理文字訊息 ===
@handler.add(MessageEvent)
def handle_message(event):
    if not isinstance(event.message, TextMessage):
        return

    msg = event.message.text.strip()
    source = event.source
    user_id = getattr(source, 'group_id', None) or getattr(source, 'user_id', None)
    if not user_id:
        return

    reply = ""

    # ➕ 新增地點
    if any(msg.startswith(alias) for alias in ADD_ALIASES):
        place_input = msg.split(maxsplit=1)[-1]
        place_name = resolve_place_name(place_input)
        if place_name:
            collection.insert_one({"user_id": user_id, "name": place_name, "comment": None})
            reply = f"✅ 地點已新增：{place_name}"
        else:
            reply = "⚠️ 無法解析地點網址或名稱。"

    # 📋 顯示清單
    elif msg in ["地點", "清單"]:
        items = list(collection.find({"user_id": user_id}))
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
            def get_lat(loc):
                try:
                    result = gmaps.geocode(loc["name"])
                    return result[0]["geometry"]["location"]["lat"]
                except:
                    return 0
            items.sort(key=get_lat)
            lines = []
            for i, loc in enumerate(items, start=1):
                line = f"{i}. {loc['name']}"
                if loc.get("comment"):
                    line += f"（{loc['comment']}）"
                lines.append(line)
            reply = "📍 地點清單：\n" + "\n".join(lines)

    # 🗑️ 刪除地點
    elif re.search(DELETE_PATTERN, msg):
        index = int(re.search(DELETE_PATTERN, msg).group(1)) - 1
        items = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(items):
            name = items[index]['name']
            collection.delete_one({"_id": items[index]['_id']})
            reply = f"🗑️ 已刪除地點：{name}"
        else:
            reply = "⚠️ 指定編號無效。"

    # 📝 註解
    elif re.search(COMMENT_PATTERN, msg):
        match = re.search(COMMENT_PATTERN, msg)
        index = int(match.group(1)) - 1
        comment = match.group(2)
        items = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(items):
            collection.update_one({"_id": items[index]['_id']}, {"$set": {"comment": comment}})
            reply = f"📝 已更新註解：{items[index]['name']} → {comment}"
        else:
            reply = "⚠️ 無法註解，請確認編號正確。"

    # ❌ 清空
    elif re.match(r"(清空|全部刪除|reset)", msg):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認清空`"

    elif msg == "確認清空":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    # 📘 說明
    elif msg in ["指令", "幫助", "help"]:
        reply = (
            "📘 指令集說明：\n"
            "➕ 新增地點 [地名/地圖網址]\n"
            "🗑️ 刪除 [編號]\n"
            "📝 註解 [編號] [說明]\n"
            "📋 地點 或 清單：顯示排序後地點\n"
            "❌ 清空：刪除所有地點（需再次確認）"
        )

    if reply:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

# === 啟動伺服器（Render） ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
