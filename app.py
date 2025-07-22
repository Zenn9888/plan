import os
import re
import json
import googlemaps
from flask import Flask, request, abort
from pymongo import MongoClient
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, RichMenu, RichMenuArea, RichMenuSize,
    URIAction, PostbackAction
)

# ✅ 載入環境變數
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# ✅ 初始化
app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(os.getenv("MONGO_URL", "mongodb://localhost:27017"))
db = client["linebot"]
locations_col = db["locations"]

# ✅ 預設首頁（解決 404）
@app.route("/")
def index():
    return "Line Bot is running!"

# ✅ Webhook 接收事件
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)

    return "OK"

# ✅ 處理訊息事件
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    if msg.lower() in ["reset", "清除", "清空", "全部刪除"]:
        locations_col.delete_many({"user_id": user_id})
        line_bot_api.reply_message(event.reply_token, TextSendMessage("✅ 已清除所有地點。"))
        return

    if msg.startswith("新增 "):
        keyword = msg[3:].strip()
        name, lat, lng, address = get_location_info(keyword)

        if not name:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("❌ 找不到地點，請確認輸入。"))
            return

        # ✅ 儲存 MongoDB
        locations_col.insert_one({
            "user_id": user_id,
            "input": keyword,
            "name": name,
            "lat": lat,
            "lng": lng,
            "address": address
        })

        reply = f"📍 已新增地點：{keyword}\n➡️ 解析：{name}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 預設提示
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(
        alt_text="Line Bot 功能選單",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "請輸入地點關鍵字", "weight": "bold", "size": "lg"},
                    {"type": "text", "text": "例如：新增 台北101", "size": "sm", "color": "#888888"}
                ]
            }
        }
    ))

# ✅ 地點解析（支援 Maps 短網址與關鍵字）
def get_location_info(keyword):
    try:
        if "maps.app.goo.gl" in keyword:
            resolved = requests.get(keyword, allow_redirects=True, timeout=5).url
            match = re.search(r"/place/([^/]+)", resolved)
            if match:
                keyword = match.group(1).replace("+", " ")

        result = gmaps.geocode(keyword)
        if not result:
            return None, None, None, None

        name = result[0].get("formatted_address")
        location = result[0]["geometry"]["location"]
        return name, location["lat"], location["lng"], name
    except Exception as e:
        print("地點查詢失敗:", e)
        return None, None, None, None

# ✅ RichMenu 建立與綁定（每次執行都檢查）
def create_rich_menu():
    richmenus = line_bot_api.get_rich_menu_list()
    if richmenus:
        return

    menu = RichMenu(
        size=RichMenuSize(width=2500, height=843),
        selected=True,
        name="MainMenu",
        chat_bar_text="≡ 功能選單",
        areas=[
            RichMenuArea(
                bounds={"x": 0, "y": 0, "width": 1250, "height": 843},
                action=PostbackAction(label="新增地點", data="add")
            ),
            RichMenuArea(
                bounds={"x": 1250, "y": 0, "width": 1250, "height": 843},
                action=PostbackAction(label="清空", data="clear")
            ),
        ]
    )

    rich_menu_id = line_bot_api.create_rich_menu(menu)
    with open("menu.png", "rb") as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)

    line_bot_api.set_default_rich_menu(rich_menu_id)
    print("✅ RichMenu 已建立並設為預設")

# ✅ 啟動
if __name__ == "__main__":
    create_rich_menu()
    app.run(host="0.0.0.0", port=10000)
