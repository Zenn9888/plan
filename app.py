import os
import re
import json
from flask import Flask, request, abort
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient, ReplyMessageRequest
from linebot.v3.messaging.models import TextMessage, FlexMessage
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks import MessageEvent

import googlemaps
from pymongo import MongoClient
from utils import (
    create_flex_message, get_coordinates, get_sorted_route_url,
    extract_location_from_url, create_static_map_url,
    show_location_list, clear_locations, add_location
)


# ✅ 初始化 Flask
app = Flask(__name__)

# ✅ 環境變數
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# ✅ 初始化 LINE Bot SDK v3
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(configuration)
handler = WebhookHandler(CHANNEL_SECRET)

# ✅ 初始化 Google Maps 與 MongoDB
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["linebot"]
collection = db["locations"]

# ✅ Webhook 入口
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("x-line-signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Webhook Error:", e)
        abort(400)

    return "OK"

# ✅ 處理訊息事件
@handler.add(MessageEvent)
def handle_message(event):
    message = event.message
    user_id = event.source.user_id

    if not isinstance(message, TextMessageContent):
        return

    msg = message.text.strip()

    if re.search(r"(地點清單|行程|目前地點)", msg):
        reply = show_location_list(user_id, collection)
    elif re.search(r"(清空|全部刪除|reset)", msg):
        reply = clear_locations(user_id, collection)
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
            reply = add_location(user_id, place["name"], place["lat"], place["lng"], collection)
        else:
            reply = "無法解析 Google Maps 短網址中的地點。"
    elif re.search(r"(新增|加入|add|地點)", msg):
        query = re.sub(r"(新增|加入|add|地點)", "", msg).strip()
        if query:
            result = get_coordinates(query, gmaps)
            if result:
                reply = add_location(user_id, query, result["lat"], result["lng"], collection)
            else:
                reply = f"找不到地點「{query}」。"
        else:
            reply = "請輸入地點名稱，例如：新增 台北101"
    else:
        flex = create_flex_message()
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex]
            )
        )
        return

    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply)]
        )
    )

# ✅ 啟動伺服器
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
