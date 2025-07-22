import os
import re
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhook.models import Event
from linebot.v3.messaging import MessagingApi, Configuration, ReplyMessageRequest
from linebot.v3.messaging.models import TextMessage, FlexMessage
import googlemaps
from pymongo import MongoClient
from utils import (
    create_flex_message, get_coordinates, get_sorted_route_url,
    extract_location_from_url, create_static_map_url,
    show_location_list, clear_locations, add_location
)

# ✅ 初始化 Flask
app = Flask(__name__)

# ✅ 初始化環境變數
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# ✅ 初始化 LINE BOT
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
line_bot_api = MessagingApi(configuration)

# ✅ 初始化 Google Maps 與 MongoDB
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["linebot"]
collection = db["locations"]

# ✅ Webhook 路徑
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

# ✅ 處理文字訊息
@handler.add(Event)
def handle_message(event: Event):
    if event.type != "message" or event.message.type != "text":
        return

    user_id = event.source.user_id
    msg = event.message.text.strip()

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
            reply = "❌ 無法解析 Google Maps 短網址中的地點。"

    elif re.search(r"(新增|加入|add|地點)", msg):
        query = re.sub(r"(新增|加入|add|地點)", "", msg).strip()
        if query:
            result = get_coordinates(query, gmaps)
            if result:
                reply = add_location(user_id, query, result["lat"], result["lng"], collection)
            else:
                reply = f"❌ 找不到地點「{query}」。"
        else:
            reply = "請輸入地點名稱，例如：新增 台北101"

    else:
        # 預設回覆 Flex 提示卡片
        flex = create_flex_message()
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[flex]
        ))
        return

    # ⬆️ 如果是文字回覆
    line_bot_api.reply_message(ReplyMessageRequest(
        reply_token=event.reply_token,
        messages=[TextMessage(text=reply)]
    ))

# ✅ 啟動 Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
