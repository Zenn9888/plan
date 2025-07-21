# ✅ 自動安裝所需套件
import subprocess
import sys

required = ['flask', 'line-bot-sdk', 'python-dotenv', 'folium', 'pymongo', 'googlemaps']
for pkg in required:
    try:
        __import__(pkg.replace('-', '_'))
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import json, os
from dotenv import load_dotenv
import googlemaps

# ✅ 載入環境變數
load_dotenv()
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
gmaps = googlemaps.Client(key=os.getenv("GOOGLE_MAPS_API_KEY"))

# ✅ 地點儲存
STORAGE_FILE = "storage.json"

def load_storage():
    if not os.path.exists(STORAGE_FILE):
        return {}
    with open(STORAGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_storage(data):
    with open(STORAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_place(user_id, place):
    data = load_storage()
    data.setdefault(user_id, [])
    if place not in data[user_id]:
        data[user_id].append(place)
    save_storage(data)

def delete_place(user_id, place):
    data = load_storage()
    if user_id in data and place in data[user_id]:
        data[user_id].remove(place)
    save_storage(data)

def get_places(user_id):
    data = load_storage()
    return data.get(user_id, [])

# ✅ Geocoding & 排序
def get_latlng(address):
    try:
        result = gmaps.geocode(address)
        if result:
            location = result[0]['geometry']['location']
            return (location['lat'], location['lng'])
    except:
        return None
    return None

def sort_places_by_distance(origin, places):
    origin_latlng = get_latlng(origin)
    destinations = [get_latlng(place) for place in places]
    names_with_coords = list(zip(places, destinations))
    names_with_coords = [(name, coord) for name, coord in names_with_coords if coord]

    if not origin_latlng or not names_with_coords:
        return []

    result = gmaps.distance_matrix(
        origins=[origin_latlng],
        destinations=[coord for _, coord in names_with_coords],
        mode="driving"
    )

    distances = result['rows'][0]['elements']
    sorted_places = sorted(zip(names_with_coords, distances), key=lambda x: x[1].get('distance', {}).get('value', float('inf')))
    return [place for (place, _), _ in sorted_places]

# ✅ 快速選單
def get_quick_reply():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="➕ 增加地點", text="增加地點")),
        QuickReplyButton(action=MessageAction(label="🗑️ 刪除地點", text="刪除地點")),
        QuickReplyButton(action=MessageAction(label="📍 目前地點", text="目前地點")),
        QuickReplyButton(action=MessageAction(label="🧭 排序地點", text="排序")),
        QuickReplyButton(action=MessageAction(label="🗺️ 地圖路線", text="地圖路線")),
    ])

@app.route("/")
def index():
    return "Line Bot 正常運行中！"

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
    user_id = event.source.user_id

    if text == "選單":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請選擇功能：", quick_reply=get_quick_reply()))
        return

    if text.startswith("增加地點"):
        place = text.replace("增加地點", "").strip()
        if place:
            add_place(user_id, place)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"✅ 已增加地點：{place}", quick_reply=get_quick_reply()))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入：增加地點 地點名稱"))
        return

    if text.startswith("刪除地點"):
        place = text.replace("刪除地點", "").strip()
        if place:
            delete_place(user_id, place)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"🗑️ 已刪除地點：{place}", quick_reply=get_quick_reply()))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入：刪除地點 地點名稱"))
        return

    if text == "目前地點":
        places = get_places(user_id)
        if places:
            msg = "\n".join(f"{i+1}. {p}" for i, p in enumerate(places))
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"📋 目前地點：\n{msg}", quick_reply=get_quick_reply()))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("📭 目前沒有地點"))
        return

    if text == "排序":
        places = get_places(user_id)
        if places:
            sorted_places = sort_places_by_distance("台北車站", places)
            if sorted_places:
                msg = "\n".join(f"{i+1}. {p}" for i, p in enumerate(sorted_places))
                line_bot_api.reply_message(event.reply_token, TextSendMessage(
                    text=f"📍 排序結果（從台北車站出發）：\n{msg}", quick_reply=get_quick_reply()))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage("⚠️ 無法定位地點，請確認名稱正確"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("📭 目前沒有地點"))
        return

    if text == "地圖路線":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="🗺️ 地圖功能開發中，請稍候！", quick_reply=get_quick_reply()))
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(
        text="請輸入『選單』來使用功能。", quick_reply=get_quick_reply()))

if __name__ == "__main__":
    app.run(port=10000, host="0.0.0.0")
