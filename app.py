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

# ✅ 自動設定 RichMenu（只執行一次，若已存在則跳過）
from linebot.models import RichMenu, RichMenuArea, RichMenuBounds, MessageAction

def setup_rich_menu_once():
    existing_menus = line_bot_api.get_rich_menu_list()
    if existing_menus:
        return  # 已有 RichMenu 就跳過

    rich_menu = RichMenu(
        size={"width": 2500, "height": 843},
        selected=True,
        name="功能選單",
        chat_bar_text="打開選單",
        areas=[
            RichMenuArea(bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                         action=MessageAction(label="新增地點", text="新增地點 台北101")),
            RichMenuArea(bounds=RichMenuBounds(x=834, y=0, width=833, height=843),
                         action=MessageAction(label="顯示地點", text="地點清單")),
            RichMenuArea(bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                         action=MessageAction(label="排序路線", text="排序路線"))
        ]
    )

    rich_menu_id = line_bot_api.create_rich_menu(rich_menu)
    with open("static/menu.png", "rb") as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)

    line_bot_api.set_default_rich_menu(rich_menu_id)

# ✅ 設定一次 RichMenu
setup_rich_menu_once()

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

    if re.search(r"(地點清單|行程|目前地點)", msg):
        reply = show_location_list(user_id, collection)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if re.search(r"(清空|全部刪除|reset)", msg):
        reply = clear_locations(user_id, collection)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if re.search(r"(排序|路線|最短路徑)", msg):
        docs = list(collection.find({"user_id": user_id}))
        if len(docs) < 2:
            reply = "請先新增至少兩個地點再排序。"
        else:
            locations = [(doc["name"], doc["lat"], doc["lng"]) for doc in docs]
            reply = get_sorted_route_url(locations, GOOGLE_API_KEY)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if "maps.app.goo.gl" in msg:
        place = extract_location_from_url(msg, gmaps)
        if place:
            reply = add_location(user_id, place["name"], place["lat"], place["lng"], collection)
        else:
            reply = "無法解析 Google Maps 短網址中的地點。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
