# ✅ 自動安裝所需套件
import subprocess
import sys

required = ['flask', 'line-bot-sdk', 'python-dotenv', 'folium', 'pymongo']
for pkg in required:
    try:
        __import__(pkg.replace('-', '_'))
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import json
import os

# 載入環境變數（Channel Access Token 與 Secret）
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# 使用簡單的 JSON 儲存使用者地點
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

    # 快速回應選單
    if text == "選單":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請選擇功能：", quick_reply=get_quick_reply())
        )
        return

    # 增加地點
    if text.startswith("增加地點"):
        place = text.replace("增加地點", "").strip()
        if place:
            add_place(user_id, place)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"✅ 已增加地點：{place}",
                quick_reply=get_quick_reply()
            ))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入：增加地點 地點名稱"))
        return

    # 刪除地點
    if text.startswith("刪除地點"):
        place = text.replace("刪除地點", "").strip()
        if place:
            delete_place(user_id, place)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"🗑️ 已刪除地點：{place}",
                quick_reply=get_quick_reply()
            ))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入：刪除地點 地點名稱"))
        return

    # 顯示目前地點
    if text == "目前地點":
        places = get_places(user_id)
        if places:
            msg = "\n".join(f"{i+1}. {p}" for i, p in enumerate(places))
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"📋 目前地點：\n{msg}",
                quick_reply=get_quick_reply()
            ))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("📭 目前沒有地點"))
        return

    # 排序地點（座標未加，先用原順序）
    if text == "排序":
        places = get_places(user_id)
        if places:
            msg = "\n".join(f"{i+1}. {p}" for i, p in enumerate(places))  # 未排序
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"📍 排序結果（暫未含座標）：\n{msg}",
                quick_reply=get_quick_reply()
            ))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage("📭 目前沒有地點"))
        return

    # 顯示地圖路線（下一步會加）
    if text == "地圖路線":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="🗺️ 地圖功能開發中，請稍候！",
            quick_reply=get_quick_reply()
        ))
        return

    # 預設回覆
    line_bot_api.reply_message(event.reply_token, TextSendMessage(
        text="請輸入『選單』來使用功能。",
        quick_reply=get_quick_reply()
    ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
