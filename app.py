import os, re, googlemaps, requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import *
from pymongo import MongoClient
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URI)
db = client["line_bot"]
locations = db["locations"]

ADD_KEYWORDS = ["新增", "加入", "add", "地點", "+", "加", "增"]
DELETE_KEYWORDS = ["刪除", "remove", "delete", "減少"]
CLEAR_KEYWORDS = ["清空", "清除", "全部刪除", "reset"]

def find_lat_lng(name):
    try:
        if "maps.app.goo.gl" in name:
            res = requests.get(name, allow_redirects=True, timeout=5)
            name = res.url.split("/place/")[-1].split("/")[0].replace("+", " ")
        result = gmaps.geocode(name)
        if result:
            address = result[0]["formatted_address"]
            lat = result[0]["geometry"]["location"]["lat"]
            lng = result[0]["geometry"]["location"]["lng"]
            return address, lat, lng
        return None, None, None
    except:
        return None, None, None

def send_flex_hint(reply_token):
    bubble = BubbleContainer(
        direction="ltr",
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="📌 功能提示", weight="bold", size="lg"),
                TextComponent(text="➕ 新增地點：新增 台北101", size="sm"),
                TextComponent(text="➖ 刪除地點：刪除 台北101", size="sm"),
                TextComponent(text="🧹 清空所有：清空", size="sm"),
                TextComponent(text="🧭 地點排序：排序", size="sm"),
            ]
        )
    )
    message = FlexSendMessage(alt_text="功能提示", contents=bubble)
    line_bot_api.reply_message(reply_token, message)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    reply_token = event.reply_token

    # 清空功能
    if any(key in user_message for key in CLEAR_KEYWORDS):
        locations.delete_many({})
        line_bot_api.reply_message(reply_token, TextSendMessage(text="✅ 所有地點已清空"))
        return

    # 地點排序
    if "排序" in user_message:
        locs = list(locations.find())
        if not locs:
            line_bot_api.reply_message(reply_token, TextSendMessage(text="❗目前沒有任何地點"))
            return
        waypoints = [f"{l['lat']},{l['lng']}" for l in locs]
        names = [l["name"] for l in locs]
        url = f"https://www.google.com/maps/dir/{'/'.join(waypoints)}"
        text = "📍 地點順序：\n" + "\n".join(f"{i+1}. {name}" for i, name in enumerate(names)) + f"\n🧭 地圖路線：{url}"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=text))
        return

    # 新增地點
    for key in ADD_KEYWORDS:
        if user_message.startswith(key):
            name = user_message[len(key):].strip()
            address, lat, lng = find_lat_lng(name)
            if address:
                locations.insert_one({"name": name, "address": address, "lat": lat, "lng": lng})
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ 已加入：{name} ({address})"))
            else:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="❗找不到該地點"))
            return

    # 刪除地點
    for key in DELETE_KEYWORDS:
        if user_message.startswith(key):
            name = user_message[len(key):].strip()
            result = locations.delete_one({"name": name})
            if result.deleted_count > 0:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🗑️ 已刪除地點：{name}"))
            else:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="❗找不到要刪除的地點"))
            return

    send_flex_hint(reply_token)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
