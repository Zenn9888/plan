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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

app = Flask(__name__)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
client = MongoClient(MONGO_URL)
db = client["line_bot_db"]
collection = db["locations"]

configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
api_instance = MessagingApi(ApiClient(configuration))
blob_api = MessagingApiBlob(ApiClient(configuration))

CHINESE_NAME_PATTERN = r'[\u4e00-\u9fff]{2,}'

ADD_ALIASES = ["新增", "加入", "增加", "+", "加", "增"]
DELETE_PATTERN = ["刪除", "移除", "del", "delete", "-", "刪", "移"]
COMMENT_PATTERN = ["註解", "備註", "note", "comment", "註", "*"]

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

def resolve_place_name(user_input):
    try:
        if "maps.app.goo.gl" in user_input:
            logging.info(f"📥 嘗試解析：{user_input}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/115.0.0.0 Safari/537.36"
            }
            resp = requests.get(user_input, headers=headers, allow_redirects=True, timeout=5)
            redirect_url = resp.url
            logging.info(f"🔁 重定向後 URL: {redirect_url}")

            if "sorry/index" in redirect_url:
                logging.warning("⚠️ 被 Google 防爬蟲擋住（進入 CAPTCHA 驗證頁），嘗試從 URL 解碼地點名稱")
                match = re.search(r"/maps/place/([^/]+)", redirect_url)
                if match:
                    encoded_name = match.group(1)
                    decoded_name = unquote(unquote(encoded_name))
                    logging.info(f"📦 解碼地點名稱：{decoded_name}")
                    result = gmaps.find_place(input=decoded_name, input_type="textquery", fields=["name"], language="zh-TW")
                    candidates = result.get("candidates")
                    if candidates:
                        name = candidates[0].get("name")
                        logging.info(f"✅ fallback API 查詢成功：{name}")
                        return name
                    else:
                        logging.warning("❌ fallback API 查不到地點")
                return "⚠️ Google 阻擋短網址解析，請改貼地點名稱或完整網址"

            if "google.com/maps/" in redirect_url:
                logging.info("📍 偵測為完整地圖頁面，嘗試用 API 查詢")
                result = gmaps.find_place(input=redirect_url, input_type="textquery", fields=["name"], language="zh-TW")
                candidates = result.get("candidates")
                if candidates:
                    name = candidates[0].get("name")
                    logging.info(f"📍 API 擷取地點：{name}")
                    return name
                else:
                    logging.warning(f"❌ API 查不到地點：{redirect_url}")
                    return "⚠️ 無法從網址解析地點"

        logging.info(f"🔍 非 maps.app.goo.gl 網址，直接查詢：{user_input}")
        result = gmaps.find_place(input=user_input, input_type="textquery", fields=["name"], language="zh-TW")
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

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    source = event.source
    user_id = getattr(source, "group_id", None) or getattr(source, "user_id", None)
    if not user_id:
        return

    reply = ""

    if any(alias in msg for alias in ADD_ALIASES):
        print("✅ 進入新增地點流程")
        raw_input = msg.split(maxsplit=1)[-1].strip()

        if raw_input in ADD_ALIASES or raw_input == "":
            reply = "⚠️ 請在指令後輸入地點名稱或地圖網址。"
            api_instance.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
            return

        added = []
        failed = []
        for line in raw_input.splitlines():
            line = line.strip()
            print(f"🧾 處理輸入行：{line}")
            if not line:
                continue
            place_name = resolve_place_name(line)
            print(f"📍 取得地點名稱：{place_name}")
            if place_name and not place_name.startswith("⚠️"):
                simplified_name = re.sub(r"^.+?[市縣區鄉鎮村里道路街巷弄段號樓]", "", place_name)
                if not simplified_name.strip():
                    simplified_name = place_name
                existing = collection.find_one({"user_id": user_id, "name": simplified_name})
                if existing:
                    print(f"⚠️ 已存在：{simplified_name}，跳過新增")
                    continue
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

    elif re.match(r"(清空|全部刪除|reset|清除)", msg):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認清空`"

    elif msg == "確認清空":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

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

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
