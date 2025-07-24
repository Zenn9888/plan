import os
import re
import requests
import googlemaps
import hmac
import hashlib
import base64
import logging
from urllib.parse import unquote, urlparse, parse_qs

from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient

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

# === ✅ 設定 Logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# === ✅ 中文正則與清理函式 ===
CHINESE_NAME_PATTERN = r'[\u4e00-\u9fff]{2,}'

def clean_place_title(name):
    name = name.replace("+", " ")
    for delimiter in ['｜', '|', '-', '、', '(', '（']:
        name = name.split(delimiter)[0]
    cleaned = name.strip()
    logging.info(f"✨ 清理後名稱：{cleaned}")
    return cleaned

def extract_chinese_name_from_q(q):
    chinese_matches = re.findall(CHINESE_NAME_PATTERN, q)
    if chinese_matches:
        name = chinese_matches[-1]
        logging.info(f"🏷️ 擷取地標名稱：{name}")
        return name
    logging.warning(f"⚠️ 找不到中文地名，fallback 使用原始 q 值：{q}")
    return q

# === ✅ Google Maps 地點名稱解析 ===
def resolve_place_name(user_input):
    try:
        if "maps.app.goo.gl" in user_input:
            logging.info(f"📥 嘗試解析：{user_input}")
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(user_input, headers=headers, allow_redirects=True, timeout=5)
            redirect_url = resp.url
            logging.info(f"🔁 重定向後 URL: {redirect_url}")

            parsed_url = urlparse(redirect_url)

            # ✅ 處理 /place/
            if "/place/" in parsed_url.path:
                parts = parsed_url.path.split("/place/")
                if len(parts) > 1:
                    name_part = parts[1].split("/")[0]
                    name = unquote(name_part)
                    if re.search(CHINESE_NAME_PATTERN, name):
                        cleaned = clean_place_title(name)
                        logging.info(f"🏷️ 擷取地標名稱（/place/）：{cleaned}")
                        return cleaned

            # ✅ 處理 ?q=
            query = parse_qs(parsed_url.query)
            if "q" in query:
                raw_q = query["q"][0]
                raw_q = unquote(raw_q)
                logging.info(f"📌 擷取 ?q=: {raw_q}")
                place_name = extract_chinese_name_from_q(raw_q)
                if place_name:
                    return place_name
                logging.warning(f"⚠️ regex 擷取失敗，嘗試用 Google API 查詢：{raw_q}")
                result = gmaps.find_place(input=raw_q, input_type="textquery", fields=["name"])
                candidates = result.get("candidates")
                if candidates:
                    name = candidates[0].get("name")
                    logging.info(f"📍 API 擷取地點：{name}")
                    return name
                else:
                    logging.warning(f"❌ API 找不到地點：{raw_q}")

        # ✅ 非短網址：直接查詢 API
        logging.info(f"🔍 非 maps.app.goo.gl 網址，直接查詢：{user_input}")
        result = gmaps.find_place(input=user_input, input_type="textquery", fields=["name"])
        candidates = result.get("candidates")
        if candidates:
            name = candidates[0].get("name")
            logging.info(f"📍 API 直接查詢結果：{name}")
            return name
        else:
            logging.warning(f"❌ API 查無結果：{user_input}")

    except Exception as e:
        logging.warning(f"❌ 最終 fallback 查詢失敗：{user_input}\n{e}")

    return "⚠️ 無法解析"

# === ✅ 指令集別名 ===
ADD_ALIASES = ["新增", "加入", "增加", "+", "加", "增"]
DELETE_PATTERN = ["刪除", "移除", "del", "delete", "-", "刪", "移"]
COMMENT_PATTERN = ["註解", "備註", "note", "comment", "註", "*"]

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
        print("✅ 進入新增地點流程")
        raw_input = msg.split(maxsplit=1)[-1].strip()

        added = []
        failed = []

        for line in raw_input.splitlines():
            line = line.strip()
            print(f"🧾 處理輸入行：{line}")
            if not line:
                continue

            place_name = resolve_place_name(line)
            print(f"📍 取得地點名稱：{place_name}")

            if place_name:
                simplified_name = re.sub(r"^.+?[市縣區鄉鎮村里道路街巷弄段號樓]", "", place_name)
                collection.insert_one({
                    "user_id": user_id,
                    "name": simplified_name,
                    "comment": None
                })
                added.append(simplified_name)
            else:
                failed.append(line)

        if added:
            reply += "✅ 地點已新增：\n" + "\n".join(f"- {name}" for name in added)
        if failed:
            reply += "\n⚠️ 無法解析以下內容：\n" + "\n".join(f"- {item}" for item in failed)
        if not reply:
            reply = "⚠️ 沒有成功新增任何地點。"

    # === 📋 顯示清單 ===
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

    # === ❌ 清空清單 ===
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
    app.run(host="0.0.0.0", port=port, debug=True)