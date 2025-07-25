import os
import re
import requests
import googlemaps
import logging
from urllib.parse import unquote
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient, ReplyMessageRequest
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent
)
from linebot.v3.messaging.models import TextMessage

# === 設定與初始化 ===
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

# === 指令別名 ===
ADD_ALIASES = ["新增", "加入", "增加", "+", "加", "增"]
DELETE_PATTERN = ["刪除", "移除", "del", "delete", "-", "刪", "移"]
COMMENT_PATTERN = ["註解", "備註", "note", "comment", "註", "*"]
CHINESE_NAME_PATTERN = r'[\u4e00-\u9fff]{2,}'

# === 工具函式 ===
def clean_place_title(name):
    name = name.replace("+", " ")
    for delimiter in ['｜', '|', '-', '、', '(', '（']:
        name = name.split(delimiter)[0]
    return name.strip()

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
                match = re.search(r"/maps/place/([^/]+)", redirect_url)
                if match:
                    decoded_name = unquote(unquote(match.group(1)))
                    result = gmaps.find_place(input=decoded_name, input_type="textquery", fields=["name"], language="zh-TW")
                    candidates = result.get("candidates")
                    if candidates:
                        return candidates[0].get("name")
                return "⚠️ Google 阻擋短網址解析，請改貼地點名稱或完整網址"

            if "google.com/maps/place/" in redirect_url:
                logging.info("📍 偵測為地圖地點頁面，擷取名稱進行 API 查詢")
                match = re.search(r"/maps/place/([^/]+)", redirect_url)
                if match:
                    encoded_name = match.group(1)
                    decoded_name = unquote(unquote(encoded_name))
                    logging.info(f"🔤 擷取並解碼名稱：{decoded_name}")
                    try:
                        result = gmaps.find_place(
                            input=decoded_name,
                            input_type="textquery",
                            fields=["name"],
                            language="zh-TW"
                        )
                        candidates = result.get("candidates")
                        if candidates:
                            name = candidates[0].get("name")
                            logging.info(f"📍 成功查詢地點名稱：{name}")
                            return name
                    except Exception as e:
                        logging.warning(f"❌ 查詢 Google Maps API 失敗：{e}")
                else:
                    logging.warning("❌ 無法從 redirect URL 擷取名稱")
                return "⚠️ 無法從網址解析地點"



        result = gmaps.find_place(input=user_input, input_type="textquery", fields=["name"], language="zh-TW")
        candidates = result.get("candidates")
        if candidates:
            return candidates[0].get("name")
    except Exception as e:
        logging.warning(f"❌ 解析失敗：{user_input}\n{e}")
    return "⚠️ 無法解析"

# === 主處理器 ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        abort(400)
    return "OK", 200

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text.strip()
    source = event.source
    user_id = getattr(source, "group_id", None) or getattr(source, "user_id", None)
    if not user_id:
        return

    reply = ""

    if any(alias in msg for alias in ADD_ALIASES):
        logging.info("✅ 進入新增地點流程")

        lines = msg.splitlines()
        content_lines = [line for line in lines if not any(alias in line for alias in ADD_ALIASES)]
        raw_input = "\n".join(content_lines).strip()

        if not raw_input:
            reply = "⚠️ 請在指令後輸入地點名稱或地圖網址。"
            api_instance.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
            return

        added = []
        duplicate = []
        failed = []

        for line in raw_input.splitlines():
            line = line.strip()
            if not line:
                continue
            logging.info(f"🧾 處理輸入行：{line}")
            place_name = resolve_place_name(line)
            logging.info(f"📍 取得地點名稱：{place_name}")

            if place_name and not place_name.startswith("⚠️"):
                simplified_name = clean_place_title(place_name)

                # 查詢是否已存在，避免 race condition 重複
                existing = collection.find_one({"user_id": user_id, "name": simplified_name})
                if existing:
                    logging.info(f"⛔️ 重複地點：{simplified_name}")
                    duplicate.append(simplified_name)
                    continue

                result = collection.insert_one({
                    "user_id": user_id,
                    "name": simplified_name,
                    "comment": None
                })

                if result.inserted_id:
                    added.append(simplified_name)
                else:
                    failed.append(line)
            else:
                failed.append(line)

        if added:
            reply += "✅ 成功新增：\n" + "\n".join(f"- {name}" for name in added) + "\n"
        if duplicate:
            reply += "⛔️ 重複地點（已略過）：\n" + "\n".join(f"- {name}" for name in duplicate) + "\n"
        if failed:
            reply += "⚠️ 解析失敗（請確認格式）：\n" + "\n".join(f"- {item}" for item in failed)

        if not (added or duplicate or failed):
            reply = "⚠️ 沒有成功新增任何地點。"

        api_instance.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply.strip())]
            )
        )
        return

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
            for i, item in enumerate(items):
                line = f"{i+1}. {item['name']}"
                if item.get("comment"):
                    line += f"（{item['comment']}）"
                lines.append(line)
            reply = "📍 地點清單：\n" + "\n".join(lines)

    elif any(p in msg for p in DELETE_PATTERN):
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

    elif any(keyword in msg for keyword in COMMENT_PATTERN):
        match = re.match(rf"({'|'.join(COMMENT_PATTERN)})\s*(\d+)\s*(.+)", msg)
        if match:
            index = int(match.group(2)) - 1
            comment = match.group(3).strip()
            items = list(collection.find({"user_id": user_id}))
            if 0 <= index < len(items):
                location_id = items[index]["_id"]
                result = collection.update_one({"_id": location_id}, {"$set": {"comment": comment}})
                if result.modified_count == 1:
                    reply = f"✏️ 已{'更新' if items[index].get('comment') else '新增'}註解：{items[index]['name']} → {comment}"
                else:
                    reply = f"⚠️ 註解儲存失敗：{items[index]['name']}"
            else:
                reply = "⚠️ 地點編號錯誤，請確認清單中的編號"
        else:
            reply = "⚠️ 請使用格式：註解 [編號] [內容]，例如：註解 2 很好玩"


    elif re.match(r"(清空|全部刪除|reset|清除)", msg):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認`"

    elif msg == "確認":
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"

    elif msg in ["指令", "幫助", "help", "/"]:
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
            api_instance.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply)]
                )
            )
        except Exception as e:
            logging.warning(f"❌ 回覆訊息錯誤：{e}")

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)