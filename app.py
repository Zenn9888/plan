import os
import re
import json
import requests
import googlemaps
from dotenv import load_dotenv
from pymongo import MongoClient
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage)
from linebot.v3.webhooks import (CallbackRequest, MessageEvent, TextMessageContent, JoinEvent, LeaveEvent)

# === 初始化 ===
load_dotenv()
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = MongoClient(MONGO_URL)
db = client["line_bot"]
collection = db["locations"]
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

# === 工具函數 ===
def extract_location(url):
    try:
        response = requests.get(url, allow_redirects=True, timeout=3)
        final_url = response.url
        match = re.search(r'@([\d.]+),([\d.]+)', final_url)
        if match:
            lat, lng = float(match.group(1)), float(match.group(2))
            place = gmaps.reverse_geocode((lat, lng))
            name = place[0]['formatted_address'] if place else "Unknown Location"
            return name, lat, lng
    except:
        return None
    return None

def sort_locations(locations):
    return sorted(locations, key=lambda x: x.get('lat', 0))  # 南到北排序

def get_owner_id(event):
    source = event.source
    if hasattr(source, 'group_id') and source.group_id:
        return source.group_id
    return source.user_id

# === Webhook 接收 ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# === 主要邏輯處理 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    owner_id = get_owner_id(event)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        def reply(text):
            line_bot_api.reply_message(ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=text)]
            ))

        # 新增地點
        if any(key in msg for key in ["新增", "加入", "加", "增"]):
            match = re.search(r'(https?://[\w./?=&%-]+)', msg)
            if match:
                url = match.group(1)
                result = extract_location(url)
                if result:
                    name, lat, lng = result
                    collection.insert_one({"owner_id": owner_id, "name": name, "lat": lat, "lng": lng, "note": ""})
                    reply(f"✅ 已新增地點：{name}")
                else:
                    reply("❌ 無法解析地點網址。請確認網址格式。")
            else:
                reply("⚠️ 請附上 Google Maps 連結。")

        # 顯示地點清單
        elif re.search(r"清單|列出|地點", msg):
            places = list(collection.find({"owner_id": owner_id}))
            if not places:
                reply("📭 尚未儲存任何地點。請貼上 Google Maps 連結來新增。")
                return
            sorted_places = sort_locations(places)
            msg_lines = []
            for i, place in enumerate(sorted_places, 1):
                line = f"{i}. {place['name']}"
                if place.get("note"):
                    line += f"（{place['note']}）"
                msg_lines.append(line)
            reply("📍 目前儲存的地點：\n" + "\n".join(msg_lines))

        # 刪除指定地點（例如：刪除 2）
        elif re.match(r"刪除\s*\d+", msg):
            match = re.match(r"刪除\s*(\d+)", msg)
            index = int(match.group(1)) - 1
            places = sort_locations(list(collection.find({"owner_id": owner_id})))
            if 0 <= index < len(places):
                place = places[index]
                collection.delete_one({"_id": place["_id"]})
                reply(f"🗑️ 已刪除第 {index+1} 個地點：{place['name']}")
            else:
                reply("❌ 無效的編號。")

        # 清空
        elif re.search(r"清空|全部刪除|reset", msg):
            count = collection.count_documents({"owner_id": owner_id})
            if count > 0:
                collection.delete_many({"owner_id": owner_id})
                reply(f"✅ 所有地點已清空（共 {count} 筆）。")
            else:
                reply("📭 沒有資料可清空。")

        # 註解地點（如：註解 2 是吃飯地點）
        elif re.match(r"註解\s*\d+", msg):
            match = re.match(r"註解\s*(\d+)\s*(.+)", msg)
            if match:
                index, note = int(match.group(1)) - 1, match.group(2)
                places = sort_locations(list(collection.find({"owner_id": owner_id})))
                if 0 <= index < len(places):
                    collection.update_one({"_id": places[index]["_id"]}, {"$set": {"note": note}})
                    reply(f"📝 已為第 {index+1} 個地點加上註解：{note}")
                else:
                    reply("❌ 無效的編號。")
            else:
                reply("⚠️ 請使用格式：註解 2 景點說明")

        # 使用說明
        elif re.search(r"指令|幫助|說明", msg):
            reply("📘 可用指令：\n" +
                  "➕ 新增地點（貼上 Google Maps 連結）\n" +
                  "📋 地點清單（列出已儲存地點）\n" +
                  "🗑️ 刪除 [編號]（例：刪除 2）\n" +
                  "🧹 清空（刪除全部地點）\n" +
                  "📝 註解 [編號] [內容]（例：註解 1 早餐）")

        else:
            reply("❓ 請輸入 '說明' 查看可用指令。")

# === 啟動伺服器 ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
