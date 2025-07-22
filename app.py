import os
import re
import json
import googlemaps
from flask import Flask, request, abort
from pymongo import MongoClient

from linebot.v3.messaging import (
    Configuration, MessagingApi, ReplyMessageRequest
)
from linebot.v3.messaging.models import TextMessage, FlexMessage
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent
from linebot.v3.webhooks.models import TextMessageContent

from utils import (
    get_coordinates, get_sorted_route_url, extract_location_from_url,
    create_static_map_url
)

app = Flask(__name__)

# ✅ 環境變數
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# ✅ LINE Bot 初始化
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(configuration)
handler = WebhookHandler(CHANNEL_SECRET)

# ✅ MongoDB & Google Maps
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
collection = client["linebot"]["locations"]

# ✅ webhook
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("x-line-signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return "OK"

# ✅ 指令別名
ADD_ALIASES = ["新增", "加入", "增加", "add", "+"]
DELETE_REGEX = r"(刪除|移除|-|移|刪)\s*(\d+)"
COMMENT_REGEX = r"(註解|備註)\s*(\d+)\s*(.+)"

# ✅ 主訊息處理
@handler.add(MessageEvent)
def handle_message(event):
    message = event.message
    user_id = event.source.user_id

    if not isinstance(message, TextMessageContent):
        return

    msg = message.text.strip()

    if re.search(r"(地點清單|目前地點|行程)", msg):
        docs = list(collection.find({"user_id": user_id}))
        if not docs:
            reply = "目前尚未加入任何地點。"
        else:
            reply = "📍 目前地點清單：\n"
            for i, doc in enumerate(docs, 1):
                note = f"（{doc['note']}）" if "note" in doc else ""
                reply += f"{i}. {doc['name']}{note}\n"

    elif re.search(r"(清空|全部刪除|reset)", msg):
        reply = "⚠️ 你確定要清空所有地點嗎？\n請回覆：「確認清空」來執行。"

    elif msg.strip() == "確認清空":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    elif match := re.match(DELETE_REGEX, msg):
        index = int(match.group(2)) - 1
        docs = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(docs):
            name = docs[index]["name"]
            collection.delete_one({"_id": docs[index]["_id"]})
            reply = f"🗑️ 已刪除第 {index+1} 個地點：{name}"
        else:
            reply = "⚠️ 編號錯誤，請確認清單中有此地點。"

    elif match := re.match(COMMENT_REGEX, msg):
        index = int(match.group(2)) - 1
        comment = match.group(3).strip()
        docs = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(docs):
            collection.update_one(
                {"_id": docs[index]["_id"]},
                {"$set": {"note": comment}}
            )
            reply = f"📝 已註解第 {index+1} 個地點為：「{comment}」"
        else:
            reply = "⚠️ 編號錯誤，請確認清單中有此地點。"

    elif re.search(r"(排序|路線|最短路徑)", msg):
        docs = list(collection.find({"user_id": user_id}))
        if len(docs) < 2:
            reply = "請先新增至少兩個地點再排序。"
        else:
            locations = [(doc["name"], doc["lat"], doc["lng"]) for doc in docs]
            reply = get_sorted_route_url(locations, GOOGLE_API_KEY)

    elif "maps.app.goo.gl" in msg:
        place = extract_location_from_url(msg, gmaps)
        if place:
            collection.insert_one({
                "user_id": user_id,
                "name": place["name"],
                "lat": place["lat"],
                "lng": place["lng"]
            })
            reply = f"✅ 已新增地點：{place['name']}"
        else:
            reply = "⚠️ 無法解析 Google Maps 短網址中的地點。"

    elif any(alias in msg for alias in ADD_ALIASES):
        name = re.sub("|".join(ADD_ALIASES), "", msg).strip()
        if name:
            result = get_coordinates(name, gmaps)
            if result:
                collection.insert_one({
                    "user_id": user_id,
                    "name": name,
                    "lat": result["lat"],
                    "lng": result["lng"]
                })
                reply = f"✅ 已新增地點：{name}"
            else:
                reply = f"⚠️ 找不到地點：{name}"
        else:
            reply = "請輸入地點名稱，例如：新增 台北101"

    else:
        # ❓ fallback 用法說明
        flex_json = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📍 指令教學", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": "➕ 新增 台北101\n📋 地點清單\n🚗 排序\n🗑️ 刪除 2\n📝 註解 3 百貨公司", "wrap": True, "margin": "md", "size": "sm"}
                ]
            }
        }
        flex = FlexMessage(alt_text="指令選單", contents=flex_json)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[flex]
        ))
        return

    line_bot_api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text=reply)]
    ))

# ✅ 執行伺服器
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
