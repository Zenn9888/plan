import os
import re
import json
import googlemaps
from flask import Flask, request, abort
from dotenv import load_dotenv
from pymongo import MongoClient
from urllib.parse import urlparse

from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient,
    ReplyMessageRequest, TextMessage,
    RichMenuSwitchAction, URIAction, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# ✅ 讀取 .env 參數
load_dotenv()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

print("✅ MONGO_URL:", MONGO_URL)

# ✅ 初始化 LINE
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
app = Flask(__name__)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

# ✅ 初始化 MongoDB
mongo_client = MongoClient(MONGO_URL)
db = mongo_client["line_bot"]
collection = db["places"]

# ✅ 指令對應詞典
aliases = {
    "新增地點": ["+", "加入", "增加", "新增"],
    "顯示地點": ["地點清單", "顯示地點"],
    "排序路線": ["排序", "規劃", "路線"],
    "刪除地點": ["刪除", "移除", "del"],
    "註解地點": ["註解", "備註"],
    "指令幫助": ["幫助", "help", "指令"]
}

# ✅ 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return 'OK'

# ✅ 處理訊息
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_id = event.source.user_id
        msg = event.message.text.strip()

        def reply(text):
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=text)]
                    )
                )

        # ✅ 新增地點
        if any(word in msg for word in aliases["新增地點"]):
            location = msg.split()[-1]
            collection.insert_one({"user_id": user_id, "location": location, "note": None})
            reply(f"✅ 地點已加入：{location}")

        # ✅ 顯示地點清單
        elif any(word in msg for word in aliases["顯示地點"]):
            places = list(collection.find({"user_id": user_id}))
            if not places:
                reply("📭 尚無任何地點")
                return
            reply_text = "📍 你的地點清單：\n"
            for idx, place in enumerate(places, 1):
                note = f"（{place['note']}）" if place.get("note") else ""
                reply_text += f"{idx}. {place['location']} {note}\n"
            reply(reply_text)

        # ✅ 個別刪除地點
        elif any(word in msg for word in aliases["刪除地點"]):
            match = re.search(r"(刪除|移除|del)\s*(\d+)", msg)
            if match:
                idx = int(match.group(2)) - 1
                places = list(collection.find({"user_id": user_id}))
                if 0 <= idx < len(places):
                    removed = places[idx]["location"]
                    collection.delete_one({"_id": places[idx]["_id"]})
                    reply(f"🗑️ 已刪除：{removed}")
                else:
                    reply("⚠️ 無效的編號")
            else:
                reply("❓ 請提供要刪除的地點編號，例如：刪除 2")

        # ✅ 註解地點
        elif any(word in msg for word in aliases["註解地點"]):
            match = re.search(r"(註解|備註)\s*(\d+)\s*[:：]?\s*(.+)", msg)
            if match:
                idx = int(match.group(2)) - 1
                note = match.group(3)
                places = list(collection.find({"user_id": user_id}))
                if 0 <= idx < len(places):
                    collection.update_one({"_id": places[idx]['_id']}, {"$set": {"note": note}})
                    reply(f"📝 已為地點 {idx+1} 加上註解：{note}")
                else:
                    reply("⚠️ 無效的編號")
            else:
                reply("📌 使用方式：註解 2 美食、備註 1 景點")

        # ✅ 清空所有地點
        elif re.search(r"(清空|全部刪除|reset)", msg):
            places = list(collection.find({"user_id": user_id}))
            if places:
                collection.delete_many({"user_id": user_id})
                reply("🧹 所有地點已清空。")
            else:
                reply("⚠️ 沒有地點可以清除。")

        # ✅ 指令說明
        elif any(word in msg for word in aliases["指令幫助"]):
            reply("📘 可用指令：\n" +
                  "- 新增：加入 台北101\n" +
                  "- 清單：地點清單\n" +
                  "- 刪除：刪除 1\n" +
                  "- 註解：註解 2 景點\n" +
                  "- 清空：reset")

        else:
            reply("❓ 請輸入有效指令，輸入『幫助』查看用法。")

    except Exception as e:
        print("❌ handler error:", e)

if __name__ == "__main__":
    app.run(port=5000)
