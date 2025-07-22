import os
import re
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FlexSendMessage
import googlemaps
from pymongo import MongoClient
from urllib.parse import urlparse
from utils import (
    create_flex_message, get_coordinates, get_sorted_route_url,
    extract_location_from_url, create_static_map_url,
    show_location_list, clear_locations, add_location
)

app = Flask(__name__)

# 讀取環境變數
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))
db = client["linebot"]
collection = db["locations"]

# 初始化 RichMenu（只需執行一次）
from richmenu_setup import setup_rich_menu
setup_rich_menu(CHANNEL_ACCESS_TOKEN)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Webhook Error:", e)
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    # 🔹 清單
    if re.search(r"(地點清單|行程|目前地點)", msg):
        reply = show_location_list(user_id, collection)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 🔹 清空
    if re.search(r"(清空|全部刪除|reset)", msg):
        reply = clear_locations(user_id, collection)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 🔹 排序
    if re.search(r"(排序|路線|最短路徑)", msg):
        docs = list(collection.find({"user_id": user_id}))
        if len(docs) < 2:
            reply = "請先新增至少兩個地點再排序。"
        else:
            locations = [(doc["name"], doc["lat"], doc["lng"]) for doc in docs]
            reply = get_sorted_route_url(locations, GOOGLE_API_KEY)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 🔹 Google Maps 短網址
    if "maps.app.goo.gl" in msg:
        place = extract_location_from_url(msg, gmaps)
        if place:
            reply = add_location(user_id, place["name"], place["lat"], place["lng"], collection)
        else:
            reply = "無法解析 Google Maps 短網址中的地點。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 🔹 加地點（模糊搜尋）
    if re.search(r"(新增|加入|add|地點)", msg):
        query = re.sub(r"(新增|加入|add|地點)", "", msg).strip()
        if query:
            result = get_coordinates(query, gmaps)
            if result:
                reply = add_location(user_id, query, result["lat"], result["lng"], collection)
            else:
                reply = f"找不到地點「{query}」。"
        else:
            reply = "請輸入地點名稱，例如：新增 台北101"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 預設提示
    flex = create_flex_message()
    line_bot_api.reply_message(event.reply_token, flex)

if __name__ == "__main__":
    app.run()
