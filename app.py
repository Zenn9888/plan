import os
from flask import Flask, request, abort
from pymongo import MongoClient
import googlemaps
from dotenv import load_dotenv

# ✅ Line Bot v3 SDK
from linebot.v3.webhook import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, TextMessage, ReplyMessageRequest,
    CreateRichMenuRequest, RichMenuArea, RichMenuBounds,
    MessageAction, RichMenuSize
)
from linebot.v3.exceptions import InvalidSignatureError, ApiException

load_dotenv()
app = Flask(__name__)

# ✅ 初始化 Line Messaging API v3
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
messaging_api = MessagingApi(configuration)
handler = WebhookHandler(CHANNEL_SECRET)

# ✅ Google Maps API
gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

# ✅ MongoDB
client = MongoClient(os.getenv("MONGODB_URI"))
db = client["linebot"]
col = db["locations"]

# ✅ 建立 Rich Menu
def setup_rich_menu():
    try:
        menus = messaging_api.get_rich_menu_list()
        if menus.rich_menus:
            print("✅ Rich Menu 已存在")
            return

        rich_menu = CreateRichMenuRequest(
            size=RichMenuSize(width=2500, height=843),
            selected=True,
            name="主選單",
            chat_bar_text="打開選單",
            areas=[
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                    action=MessageAction(label="新增地點", text="新增 台北101 晚餐")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=834, y=0, width=833, height=843),
                    action=MessageAction(label="查看清單", text="地點清單")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                    action=MessageAction(label="清空地點", text="清空")
                )
            ]
        )

        created_menu = messaging_api.create_rich_menu(rich_menu)
        rich_menu_id = created_menu.rich_menu_id

        with open("menu.jpg", 'rb') as f:
            messaging_api.set_rich_menu_image(rich_menu_id, "image/jpeg", f)
        messaging_api.set_default_rich_menu(rich_menu_id)
        print("✅ 已建立並設為預設 Rich Menu")

    except ApiException as e:
        print(f"❌ Rich Menu 建立失敗：{e}")

# ✅ webhook 入口
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ✅ 接收訊息處理
@handler.add(event_type="message")
def handle_message(event):
    try:
        user_id = event.source.user_id
        msg = event.message.text.strip()

        if msg.startswith("新增") or msg.startswith("加入") or msg.startswith("add"):
            parts = msg.split(" ", 2)
            if len(parts) < 2:
                _reply(event.reply_token, "請提供要新增的地點名稱。")
                return
            place = parts[1]
            note = parts[2] if len(parts) > 2 else ""
            geocode = gmaps.geocode(place)
            if not geocode:
                _reply(event.reply_token, "找不到該地點。")
                return
            loc = geocode[0]['geometry']['location']
            col.insert_one({
                "user_id": user_id,
                "name": place,
                "note": note,
                "lat": loc['lat'],
                "lng": loc['lng']
            })
            _reply(event.reply_token, f"✅ 已加入：{place} ({note})")

        elif msg in ["地點清單", "查看清單"]:
            data = list(col.find({"user_id": user_id}))
            if not data:
                _reply(event.reply_token, "尚未加入任何地點。")
                return
            result = "📍 目前清單：\n\n" + "\n".join(
                [f"{i+1}. {d['name']} - {d.get('note', '')}" for i, d in enumerate(data)]
            )
            _reply(event.reply_token, result)

        elif msg in ["清空", "全部刪除", "reset"]:
            col.delete_many({"user_id": user_id})
            _reply(event.reply_token, "✅ 已清空所有地點。")

    except ApiException as e:
        print(f"❌ LINE API 錯誤：{e}")

# ✅ 回覆工具函式
def _reply(reply_token, text):
    messaging_api.reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)]
        )
    )

# ✅ 主程式
if __name__ == "__main__":
    setup_rich_menu()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
