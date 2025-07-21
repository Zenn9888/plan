import os
import re
import requests
from flask import Flask, request, abort
from pymongo import MongoClient
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

load_dotenv()

app = Flask(__name__)

# LINE Bot 驗證
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# MongoDB Atlas 設定
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["line_bot"]
locations = db["locations"]

# Google Geocoding API
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
def geocode_place(place):
    url = f"https://maps.googleapis.com/maps/api/geocode/json"
    params = {"address": place, "key": GOOGLE_API_KEY}
    resp = requests.get(url, params=params).json()
    if resp["status"] == "OK":
        result = resp["results"][0]
        return {
            "name": result["formatted_address"],
            "lat": result["geometry"]["location"]["lat"],
            "lng": result["geometry"]["location"]["lng"]
        }
    return None

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
    text = event.message.text.strip()

    # ✅ 增加地點 XX
    if text.startswith("增加地點"):
        query = text.replace("增加地點", "").strip()
        if not query:
            reply = "請輸入地點名稱，例如：增加地點 台北101"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
            return

        result = geocode_place(query)
        if result:
            locations.insert_one(result)
            reply = f"✅ 已成功加入地點：\n{result['name']}\n座標：{result['lat']}, {result['lng']}"
        else:
            reply = "❌ 查無此地點，請確認地點名稱是否正確。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 回覆說明
    if text in ["使用說明", "help", "？"]:
        reply = "📍 請輸入：「增加地點 + 地名」\n例如：增加地點 台北101"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
