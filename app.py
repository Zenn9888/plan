import os
import re
import requests
import googlemaps
import hmac
import hashlib
import base64
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
from urllib.parse import unquote, urlparse, parse_qs

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi,
    MessagingApiBlob,
    Configuration,
    ApiClient,
    ReplyMessageRequest,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging.models import TextMessage


# === ✅ 載入環境變數 ===
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

# === ✅ 初始化服務 ===
app = Flask(__name__)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["line_bot_db"]
collection = db["locations"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
api_instance = MessagingApi(ApiClient(configuration))
blob_api = MessagingApiBlob(ApiClient(configuration))

# === ✅ 指令集別名與正則 ===
ADD_ALIASES = ["新增", "加入", "增加", "+", "加", "增"]
DELETE_PATTERN = ["刪除", "移除", "del", "delete","-","刪","移"]
COMMENT_PATTERN = ["註解", "備註", "note", "comment","註","*"]

def verify_signature(secret, body, signature):
    hash = hmac.new(secret.encode('utf-8'), body.encode('utf-8'), hashlib.sha256).digest()
    computed_signature = base64.b64encode(hash).decode('utf-8')
    return hmac.compare_digest(computed_signature, signature)

# === ✅ 解析 Google Maps 短網址成地名 ===
def resolve_place_name(input_text):
    try:
        if input_text.startswith("http"):
            print(f"📥 嘗試解析短網址: {input_text}")
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            final_url = res.url
            print(f"🔁 重定向後的 URL: {final_url}")

            parsed_url = urlparse(final_url)
            if "google.com/maps" in parsed_url.netloc:
                query = parse_qs(parsed_url.query)
                if "q" in query:
                    place_query = query["q"][0]
                    print(f"✅ 抽出 q 地點: {place_query}")
                    return place_query

        # 若為地名或已解碼網址
        gmaps_result = gmaps.find_place(input_text, input_type="textquery", fields=["name"])
        if gmaps_result.get("candidates"):
            return gmaps_result["candidates"][0]["name"]
    except Exception as e:
        print(f"❌ 地點解析錯誤: {e}")
    return None


# === ✅ Webhook 入口 ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        print("❌ Webhook Error:", e)
        abort(400)
    return "OK"

# === ✅ 訊息處理主函式 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    source = event.source
    user_id = getattr(source, "group_id", None) or getattr(source, "user_id", None)
    if not user_id:
        return

    reply = ""

    # === ➕ 新增地點 ===
    if any(alias in msg for alias in ADD_ALIASES):
        raw_input = msg.split(maxsplit=1)[-1].strip()

        added = []
        failed = []

        for line in raw_input.splitlines():
            line = line.strip()
            if not line:
                continue
            place_name = resolve_place_name(line)
            if place_name:
                # 簡化名稱，只保留最後的地標名稱（排除地址）
                simplified_name = re.sub(r"^.+?[市縣區鄉鎮村里道路街巷弄段號樓]", "", place_name)
                collection.insert_one({
                    "user_id": user_id,
                    "name": simplified_name,
                    "comment": None
                })
                added.append(simplified_name)
            else:
                failed.append(line)

        reply = ""
        if added:
            reply += "✅ 地點已新增：\n" + "\n".join(f"- {name}" for name in added)
        if failed:
            reply += "\n⚠️ 無法解析以下內容：\n" + "\n".join(f"- {item}" for item in failed)

        if not reply:
            reply = "⚠️ 沒有成功新增任何地點。"

    # === 📋 顯示清單（排序南到北） ===
    elif msg in ["地點", "清單"]:
        items = list(collection.find({"user_id": user_id}))
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
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

    # === 🗑️ 刪除地點 ===
    elif any(key in msg for key in DELETE_PATTERN):
        match = re.search(r"(\d+)", msg)
        if match:
            index = int(match.group(1)) - 1
            items = list(collection.find({"user_id": user_id}))
            if 0 <= index < len(items):
                name = items[index]["name"]
                collection.delete_one({"_id": items[index]["_id"]})
                reply = f"🗑️ 已刪除地點：{name}"
            else:
                reply = "⚠️ 指定編號無效。"

    # === 📝 註解地點 ===
    elif any(key in msg for key in COMMENT_PATTERN):
        match = re.search(r"(\d+)[\s:：]*(.+)", msg)
        if match:
            index = int(match.group(1)) - 1
            comment = match.group(2)
            items = list(collection.find({"user_id": user_id}))
            if 0 <= index < len(items):
                collection.update_one({"_id": items[index]["_id"]}, {"$set": {"comment": comment}})
                reply = f"📝 已更新註解：{items[index]['name']} → {comment}"
            else:
                reply = "⚠️ 無法註解，請確認編號正確。"

    # === ❌ 清空清單（確認機制） ===
    elif re.match(r"(清空|全部刪除|reset)", msg):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認清空`"

    elif msg == "確認":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    # === 📘 指令說明 ===
    elif msg in ["指令", "幫助", "help"]:
        reply = (
            "📘 指令集說明：\n"
            "➕ 新增地點 [地名/地圖網址]\n"
            "🗑️ 刪除 [編號]\n"
            "📝 註解 [編號] [說明]\n"
            "📋 地點 或 清單：顯示排序後地點\n"
            "❌ 清空：刪除所有地點（需再次確認）"
        )

    # === ✉️ 傳送回覆 ===
    if reply:
        try:
            print("🧪 REPLY_TOKEN:", event.reply_token)
            print("🧪 REPLY_TEXT:", reply)

            api_instance.reply_message(
                ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply)]
            )
        )
        except Exception as e:
            print("❌ 回覆訊息錯誤:", e)


# === ✅ 啟動伺服器 ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
