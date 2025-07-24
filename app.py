import os
import re
import requests
import googlemaps
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
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

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
ADD_ALIASES = ["新增", "加入", "增加"]
DELETE_PATTERN = r"刪除 (\d+)"
COMMENT_PATTERN = r"註解 (\d+)[\s:：]*(.+)"

# === ✅ 解析 Google Maps 短網址成地名 ===
def resolve_place_name(input_text):
    try:
        print(f"📥 嘗試解析：{input_text}")

        if input_text.startswith("http"):
            res = requests.get(input_text, allow_redirects=True, timeout=10)
            url = res.url
            print(f"🔁 重定向後 URL: {url}")
        else:
            url = input_text

        # 1️⃣ 如果網址中有 /place/，直接擷取地名
        place_match = re.search(r"/place/([^/]+)", url)
        if place_match:
            name = unquote(place_match.group(1))
            print(f"🏷️ 擷取 /place/: {name}")
            return name

        # 2️⃣ 如果網址中有 q=，不要直接用，改用 q 的值去查 API 取得地點名稱
        q_match = re.search(r"[?&]q=([^&]+)", url)
        if q_match:
            address_text = unquote(q_match.group(1))
            print(f"📌 擷取 ?q=: {address_text}")
            # 這裡才是正解：用地址查地名
            result = gmaps.find_place(address_text, input_type="textquery", fields=["place_id"])
            if result.get("candidates"):
                place_id = result["candidates"][0]["place_id"]
                details = gmaps.place(place_id=place_id, fields=["name"])
                name = details["result"]["name"]
                print(f"✅ API 解析名稱：{name}")
                return name

        # 3️⃣ 最後 fallback：直接查輸入值
        result = gmaps.find_place(input_text, input_type="textquery", fields=["place_id"])
        if result.get("candidates"):
            place_id = result["candidates"][0]["place_id"]
            details = gmaps.place(place_id=place_id, fields=["name"])
            name = details["result"]["name"]
            print(f"✅ 最終 API 名稱：{name}")
            return name

    except Exception as e:
        print(f"❌ 錯誤：{e}")
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
        place_input = msg.split(maxsplit=1)[-1]
        place_name = resolve_place_name(place_input)
        if place_name:
            # 僅取地標名稱部分（排除地址）
            simplified_name = re.sub(r"^.+?[市縣區鄉鎮村里道路街巷弄段號號樓]", "", place_name)
            collection.insert_one({"user_id": user_id, "name": simplified_name, "comment": None})
            reply = f"✅ 地點已新增：{simplified_name}"
        else:
            reply = "⚠️ 無法解析地點網址或名稱。"

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
    elif re.search(DELETE_PATTERN, msg):
        index = int(re.search(DELETE_PATTERN, msg).group(1)) - 1
        items = list(collection.find({"user_id": user_id}))
        if 0 <= index < len(items):
            name = items[index]["name"]
            collection.delete_one({"_id": items[index]["_id"]})
            reply = f"🗑️ 已刪除地點：{name}"
        else:
            reply = "⚠️ 指定編號無效。"

    # === 📝 註解地點 ===
    elif re.search(COMMENT_PATTERN, msg):
        match = re.search(COMMENT_PATTERN, msg)
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

    elif msg == "確認清空":
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
