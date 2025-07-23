import os
import re
import json
import requests
from flask import Flask, request, abort
from pymongo import MongoClient
from dotenv import load_dotenv
import googlemaps

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    SignatureValidator, CallbackRequest, MessageEvent, TextMessageContent
)

load_dotenv()

app = Flask(__name__)

# 🔐 環境變數
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# ⛓️ LINE SDK 初始化
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
api_client = ApiClient(configuration)
line_bot_api = MessagingApi(api_client)
handler = WebhookHandler(CHANNEL_SECRET)
signature_validator = SignatureValidator(CHANNEL_SECRET)

# 🌍 Google Maps Client
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

# 🗃️ MongoDB 設定
client = MongoClient(MONGO_URL)
db = client["line_bot"]
collection = db["locations"]

# 🧠 指令別名對照表
command_aliases = {
    "add": ["新增", "加入", "增加"],
    "clear": ["清空", "全部刪除", "reset"],
    "delete": ["刪除", "移除", "del", "delete"],
    "note": ["註解", "備註"],
    "list": ["清單", "列表", "地點"]
}

def match_command(msg, key):
    return any(alias in msg for alias in command_aliases[key])

def extract_place_from_url(url):
    try:
        res = requests.get(url, allow_redirects=True)
        if "place_id=" in res.url:
            place_id = re.search(r"place_id=([^&]+)", res.url).group(1)
            place = gmaps.place(place_id=place_id)
        else:
            place = gmaps.find_place(input=res.url, input_type="textquery", fields=["name", "geometry", "formatted_address"])
        if "result" in place:
            name = place["result"]["name"]
            location = place["result"]["geometry"]["location"]
            return name, location["lat"], location["lng"]
        elif "candidates" in place and place["candidates"]:
            c = place["candidates"][0]
            return c["name"], c["geometry"]["location"]["lat"], c["geometry"]["location"]["lng"]
    except:
        pass
    return None, None, None

def geocode_place(text):
    try:
        result = gmaps.geocode(text)
        if result:
            name = result[0]["formatted_address"]
            location = result[0]["geometry"]["location"]
            return name, location["lat"], location["lng"]
    except:
        pass
    return None, None, None

def sort_by_lat(locations):
    return sorted(locations, key=lambda x: x["lat"])

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature_validator)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    user_id = event.source.group_id if event.source.type == "group" else event.source.user_id
    reply = "請輸入有效指令，輸入「指令說明」查看用法。"

    # 📌 新增地點
    if match_command(msg, "add"):
        location_text = re.sub(r"^(新增|加入|增加)地點[:： ]*", "", msg)
        name, lat, lng = (None, None, None)
        if "http" in location_text:
            name, lat, lng = extract_place_from_url(location_text)
        else:
            name, lat, lng = geocode_place(location_text)
        if name:
            collection.insert_one({"user_id": user_id, "name": name, "lat": lat, "lng": lng, "note": ""})
            reply = f"✅ 已新增地點：{name}"
        else:
            reply = "❌ 無法解析地點網址或名稱"

    # 🗑️ 清空
    elif match_command(msg, "clear"):
        reply = "⚠️ 確定要清空所有地點嗎？請回覆「確認清空」"
    elif msg == "確認清空":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    # ❌ 刪除編號
    elif match_command(msg, "delete"):
        number = re.search(r"\d+", msg)
        if number:
            index = int(number.group()) - 1
            locations = list(collection.find({"user_id": user_id}))
            if 0 <= index < len(locations):
                name = locations[index]["name"]
                collection.delete_one({"_id": locations[index]["_id"]})
                reply = f"🗑️ 已刪除：{name}"
            else:
                reply = "❌ 無效編號"
        else:
            reply = "請輸入要刪除的地點編號，如：刪除 2"

    # 📝 註解地點
    elif match_command(msg, "note"):
        match = re.search(r"註解\s*(\d+)\s+(.+)", msg)
        if match:
            index = int(match.group(1)) - 1
            note = match.group(2)
            locations = list(collection.find({"user_id": user_id}))
            if 0 <= index < len(locations):
                collection.update_one({"_id": locations[index]["_id"]}, {"$set": {"note": note}})
                reply = f"📝 已為「{locations[index]['name']}」添加註解"
            else:
                reply = "❌ 無效地點編號"
        else:
            reply = "格式錯誤，請使用：註解 2 這裡很好玩"

    # 📋 地點清單
    elif match_command(msg, "list"):
        locations = list(collection.find({"user_id": user_id}))
        if not locations:
            reply = "📭 尚未新增任何地點"
        else:
            locations = sort_by_lat(locations)
            lines = []
            for i, loc in enumerate(locations, 1):
                note = f"（{loc['note']}）" if loc.get("note") else ""
                lines.append(f"{i}. {loc['name']}{note}")
            reply = "\n".join(lines)

    # 📖 指令說明
    elif "指令" in msg or "幫助" in msg:
        reply = (
            "📘 指令說明：\n"
            "➕ 新增地點 [名稱 或 Google Maps 網址]\n"
            "🗑️ 刪除 [編號]\n"
            "📝 註解 [編號] [說明]\n"
            "📋 清單 / 列表 / 地點\n"
            "♻️ 清空 / 全部刪除\n"
        )

    # 📤 回覆
    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply)]
        )
    )

# === 啟動伺服器 ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
