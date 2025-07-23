import os
import re
import requests
import googlemaps
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage
)

# ✅ 載入 .env 設定
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# ✅ 初始化
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

client = MongoClient(MONGO_URL)
db = client["line_bot_db"]
collection = db["locations"]

app = Flask(__name__)

# === 指令集別名 ===
ADD_ALIASES = ["新增", "加入", "增加"]
DELETE_PATTERN = r"刪除 (\d+)"
COMMENT_PATTERN = r"註解 (\d+)[\s:：]*(.+)"

# === 解析 Google Maps 短網址 ===
import requests
import re
import googlemaps
from urllib.parse import unquote

import requests
import re
from urllib.parse import unquote

import requests
import re
from urllib.parse import unquote

import requests
import re
from urllib.parse import unquote

import requests
import re
from urllib.parse import unquote

def resolve_place_name(input_text):
    try:
        # 檢查是否為 Google Maps 短網址
        if input_text.startswith("http"):
            # 跟蹤短網址的重定向
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            url = res.url  # 重定向後的最終 URL
            print(f"重定向後的 URL: {url}")  # 用來檢查重定向後的 URL
        else:
            url = input_text

        # 解析 /place/ 之後的部分來獲取地點名稱
        match = re.search(r"/place/([^/]+)", url)
        if match:
            return unquote(match.group(1))  # 解碼 URL，返回地點名稱

        # 進一步處理，當 URL 包含 google.com/maps/place/
        if 'google.com/maps/place/' in url:
            match = re.search(r"place/([^/]+)", url)
            if match:
                return unquote(match.group(1))  # 解碼並返回地點名稱

    except Exception as e:
        print(f"解析錯誤: {e}")
    
    return None


# === webhook ===
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return 'OK'

# === 處理訊息 ===
@handler.add(MessageEvent)
def handle_message(event):
    if not isinstance(event.message, TextMessage):
        return

    msg = event.message.text.strip()
    source = event.source
    user_id = getattr(source, 'group_id', None) or getattr(source, 'user_id', None)
    if not user_id:
        return

    reply = ""

    # 新增地點
    if any(a in msg for a in ADD_ALIASES):
        place_input = msg.split(maxsplit=1)[-1] if len(msg.split()) > 1 else ""
        
        if not place_input:
            reply = "⚠️ 請提供地點名稱或 Google Maps 網址。"
        else:
            place_name = resolve_place_name(place_input)
            if place_name:
                collection.insert_one({"user_id": user_id, "name": place_name, "comment": None})
                reply = f"✅ 地點已新增：{place_name}"
            else:
                reply = "⚠️ 無法解析地點網址或名稱。"

    # 顯示清單
    elif msg in ["地點", "清單"]:
        items = list(collection.find({"user_id": user_id}))
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
            # 排序南到北（經度）
            def get_lat(loc):
                try:
                    result = gmaps.geocode(loc["name"])
                    return result[0]["geometry"]["location"]["lat"]
                except:
                    return 0
            items.sort(key=get_lat)
            lines = []
            for i, loc in enumerate(items, start=1):
                line = f"{i}. {loc['name']}"
                if loc.get("comment"):
                    line += f"（{loc['comment']}）"
                lines.append(line)
            reply = "📍 地點清單：\n" + "\n".join(lines)

    # 刪除指定地點
    elif re.search(DELETE_PATTERN, msg):
        index = int(re.search(DELETE_PATTERN, msg).group(1)) - 1
        items = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(items):
            name = items[index]['name']
            collection.delete_one({"_id": items[index]['_id']})
            reply = f"🗑️ 已刪除地點：{name}"
        else:
            reply = "⚠️ 指定編號無效。"

    # 註解地點
    elif re.search(COMMENT_PATTERN, msg):
        match = re.search(COMMENT_PATTERN, msg)
        index = int(match.group(1)) - 1
        comment = match.group(2)
        items = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(items):
            collection.update_one({"_id": items[index]['_id']}, {"$set": {"comment": comment}})
            reply = f"📝 已更新註解：{items[index]['name']} → {comment}"
        else:
            reply = "⚠️ 無法註解，請確認編號正確。"

    # 清空地點（需二次確認）
    elif re.match(r"(清空|全部刪除|reset)", msg):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認清空`"

    elif msg == "確認清空":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    # 指令說明
    elif msg in ["指令", "幫助", "help"]:
        reply = (
            "📘 指令集說明：\n"
            "➕ 新增地點 [地名/地圖網址]\n"
            "🗑️ 刪除 [編號]\n"
            "📝 註解 [編號] [說明]\n"
            "📋 地點 或 清單：顯示排序後地點\n"
            "❌ 清空：刪除所有地點（需再次確認）"
        )

    if reply:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

# === 啟動伺服器 ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
