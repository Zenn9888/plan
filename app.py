# app.py（支援短網址地點 + rich menu + 備註 + 清單）
import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from pymongo import MongoClient
import googlemaps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# LINE Bot 設定
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# Google Maps 設定
gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

# MongoDB 設定
client = MongoClient(os.getenv("MONGODB_URI"))
db = client["linebot"]
col = db["locations"]

# Rich Menu 設定
def setup_rich_menu():
    menus = line_bot_api.get_rich_menu_list()
    if menus:
        rich_menu_id = menus[0].rich_menu_id
        line_bot_api.set_default_rich_menu(rich_menu_id)
        return

    rich_menu = RichMenu(
        size=RichMenuSize(width=2500, height=843),
        selected=True,
        name="主選單",
        chat_bar_text="打開選單",
        areas=[
            RichMenuArea(bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                         action=MessageAction(label="新增地點", text="新增 台北101 晚餐")),
            RichMenuArea(bounds=RichMenuBounds(x=834, y=0, width=833, height=843),
                         action=MessageAction(label="查看清單", text="地點清單")),
            RichMenuArea(bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                         action=MessageAction(label="清空地點", text="清空"))
        ]
    )
    rich_menu_id = line_bot_api.create_rich_menu(rich_menu=rich_menu)
    with open("menu.jpg", 'rb') as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/jpeg", f)
    line_bot_api.set_default_rich_menu(rich_menu_id)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    if msg.startswith(("新增", "加入", "add")):
        parts = msg.split(" ", 2)
        if len(parts) < 2:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請提供要新增的地點名稱。"))
            return
        place = parts[1]
        note = parts[2] if len(parts) > 2 else ""

        # ✅ 處理 maps.app.goo.gl 短網址
        if place.startswith("https://maps.app.goo.gl"):
            try:
                r = requests.get(place, allow_redirects=True)
                if r.status_code == 200:
                    real_url = r.url
                    if "/place/" in real_url:
                        place = real_url.split("/place/")[1].split("/")[0]
                        place = requests.utils.unquote(place)
            except Exception as e:
                print("短網址解析失敗:", e)
                line_bot_api.reply_message(event.reply_token, TextSendMessage("短網址解析失敗，請改用地點名稱。"))
                return

        geocode = gmaps.geocode(place)
        if not geocode:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("找不到該地點。"))
            return
        loc = geocode[0]['geometry']['location']
        col.insert_one({
            "user_id": user_id,
            "name": place,
            "note": note,
            "lat": loc['lat'],
            "lng": loc['lng']
        })
        line_bot_api.reply_message(event.reply_token, TextSendMessage(f"✅ 已加入：{place} ({note})"))

    elif msg in ["地點清單", "查看清單"]:
        data = list(col.find({"user_id": user_id}))
        if not data:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("尚未加入任何地點。"))
            return
        result = "📍 目前清單：\n\n" + "\n".join(
            [f"{i+1}. {d['name']} - {d.get('note', '')}" for i, d in enumerate(data)])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(result))

    elif msg in ["清空", "全部刪除", "reset"]:
        col.delete_many({"user_id": user_id})
        line_bot_api.reply_message(event.reply_token, TextSendMessage("✅ 已清空所有地點。"))

if __name__ == "__main__":
    setup_rich_menu()
    app.run(debug=True)
