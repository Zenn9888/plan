import os
import re
from flask import Flask, request, abort
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhook import WebhookHandler, Event
from linebot.v3.messaging import MessagingApi, Configuration, ReplyMessageRequest
from linebot.v3.messaging.models import TextMessage, FlexMessage
import googlemaps
from pymongo import MongoClient
from utils import (
    create_flex_message, get_coordinates, get_sorted_route_url,
    extract_location_from_url, create_static_map_url,
    show_location_list, clear_locations, add_location
)
# ✅ Flask 初始化
app = Flask(__name__)

# ✅ 設定環境變數（Render 平台自動讀取）
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# ✅ 初始化 LINE Bot SDK v3
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
line_bot_api = MessagingApi(configuration)
handler = WebhookHandler(CHANNEL_SECRET)

# ✅ Google Maps 與 MongoDB 初始化
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["linebot"]
collection = db["locations"]

# ✅ Webhook Endpoint
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("x-line-signature")
    body = request.get_data(as_text=True)
    print("✅ Webhook body:", body)  # 可印出接收到的 JSON 結構

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return "OK"

# ✅ 訊息事件處理
@handler.add(MessageEvent)
def handle_message(event):
    if not isinstance(event.message, TextMessageContent):
        return

    user_id = event.source.user_id
    msg = event.message.text.strip()
    print(f"✉️ 使用者 {user_id} 傳來訊息：{msg}")

    # 地點清單
    if re.search(r"(地點清單|目前地點|行程)", msg):
        reply = show_location_list(user_id, collection)

    # 清空地點
    elif re.search(r"(清空|全部刪除|reset)", msg):
        reply = clear_locations(user_id, collection)

    # 排序路線
    elif re.search(r"(排序|最短路徑|路線)", msg):
        docs = list(collection.find({"user_id": user_id}))
        if len(docs) < 2:
            reply = "請先新增至少兩個地點再排序。"
        else:
            locations = [(doc["name"], doc["lat"], doc["lng"]) for doc in docs]
            reply = get_sorted_route_url(locations, GOOGLE_API_KEY)

    # Google Maps 短網址解析
    elif "maps.app.goo.gl" in msg:
        place = extract_location_from_url(msg, gmaps)
        if place:
            reply = add_location(user_id, place["name"], place["lat"], place["lng"], collection)
        else:
            reply = "無法解析 Google Maps 短網址中的地點。"

    # 手動新增地點
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

    # 預設：顯示 Flex 選單提示
    else:
        flex = create_flex_message()
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex]
            )
        )
        return  # ⚠️ 若已回覆 Flex 就不進入下方文字回覆

    # 傳送文字回覆
    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=reply)]
        )
    )

# ✅ 啟動伺服器（Render 會使用環境變數 PORT）
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))