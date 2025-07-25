# === 開頭載入與初始化 ===
import os, re, requests, logging
from urllib.parse import unquote
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
import googlemaps

from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    MessagingApi, Configuration, ApiClient, ReplyMessageRequest
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging.models import TextMessage

load_dotenv()
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

# === API 與資料庫設定 ===
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
MONGO_URL = os.getenv("MONGO_URL")

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

# === 工具函式 ===
def clean_place_title(name):
    name = name.replace("+", " ")
    for delimiter in ['｜', '|', '-', '、', '(', '（']:
        name = name.split(delimiter)[0]
    return name.strip()

def resolve_place_name(user_input):
    try:
        if "maps.app.goo.gl" in user_input:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(user_input, headers=headers, allow_redirects=True, timeout=5)
            redirect_url = resp.url
            logging.info(f"🔁 重定向後 URL: {redirect_url}")
            if "google.com/maps/place/" in redirect_url:
                match = re.search(r"/maps/place/([^/]+)", redirect_url)
                if match:
                    decoded_name = unquote(unquote(match.group(1)))
                    result = gmaps.find_place(decoded_name, "textquery", fields=["name"], language="zh-TW")
                    if result.get("candidates"):
                        return result["candidates"][0]["name"]
            return "⚠️ 無法從網址解析地點"
        result = gmaps.find_place(user_input, "textquery", fields=["name"], language="zh-TW")
        if result.get("candidates"):
            return result["candidates"][0]["name"]
    except Exception as e:
        logging.warning(f"❌ 解析失敗：{e}")
    return "⚠️ 無法解析"

# === Webhook 路由 ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logging.info(f"📩 收到請求：{body}")
    try:
        handler.handle(body, signature)
    except Exception as e:
        logging.error(f"Webhook 錯誤：{e}")
        abort(400)
    return "OK", 200

# === 訊息處理 ===
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    reply = ""

    items = list(collection.find({"user_id": user_id}).sort("lat", 1))

    # 顯示清單
    if any(k in msg for k in ["清單", "地點"]):
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
            lines = []
            for i, item in enumerate(items):
                line = f"{i+1}. {item['name']}"
                if item.get("comment"):
                    line += f"（{item['comment']}）"
                lines.append(line)
            reply = "📍 地點清單：\n" + "\n".join(lines)

    # 清空
    elif msg in ["確認清空", "確認"]:
        collection.delete_many({"user_id": user_id})
        reply = "✅ 所有地點已清空。"
    elif any(k in msg for k in ["清空", "全部刪除", "reset"]):
        reply = "⚠️ 是否確認清空所有地點？請輸入 `確認清空`"

    # 刪除
    elif any(k in msg for k in DELETE_PATTERN):
        match = re.search(r"(\d+)", msg)
        if match:
            index = int(match.group(1)) - 1
            if 0 <= index < len(items):
                name = items[index]["name"]
                collection.delete_one({"_id": items[index]["_id"]})
                reply = f"🗑️ 已刪除地點：{name}"
            else:
                reply = "⚠️ 指定編號無效。"

    # 修改註解
    elif msg.startswith("修改註解"):
        match = re.match(r"修改註解\s*(\d+)\s+(.+?)\s+(.+)", msg)
        if match:
            index = int(match.group(1)) - 1
            old, new = match.group(2).strip(), match.group(3).strip()
            if 0 <= index < len(items):
                location = items[index]
                comment_list = location.get("comment", "").split("｜") if location.get("comment") else []
                if old in comment_list:
                    updated = [new if c == old else c for c in comment_list]
                    collection.update_one({"_id": location["_id"]}, {"$set": {"comment": "｜".join(updated)}})
                    reply = f"🔧 已修改第 {index+1} 筆地點的註解：{old} → {new}"
                else:
                    reply = f"⚠️ 找不到註解「{old}」"
            else:
                reply = "⚠️ 無效的地點編號。"
        else:
            reply = "⚠️ 請使用格式：修改註解 [編號] [原內容] [新內容]"

    # 新增註解
    elif any(msg.startswith(p) for p in COMMENT_PATTERN):
        pattern = rf"({'|'.join(re.escape(p) for p in COMMENT_PATTERN)})\s*(\d+)\s+(.+)"
        match = re.match(pattern, msg)
        if match:
            index = int(match.group(2)) - 1
            new_comment = match.group(3).strip()
            if 0 <= index < len(items):
                location = items[index]
                comment_list = location.get("comment", "").split("｜") if location.get("comment") else []
                if new_comment in comment_list:
                    reply = f"⚠️ 此註解已存在於第 {index+1} 筆地點中"
                else:
                    comment_list.append(new_comment)
                    collection.update_one({"_id": location["_id"]}, {"$set": {"comment": "｜".join(comment_list)}})
                    reply = f"📝 已為第 {index+1} 筆地點新增註解：{new_comment}"
            else:
                reply = "⚠️ 無效的地點編號。"
        else:
            reply = "⚠️ 請使用格式：註解 [編號] [內容]"

    # 幫助
    elif msg.lower() in ["help", "幫助", "指令", "/", "說明"]:
        reply = (
            "📘 指令集說明：\n"
            "➕ 新增地點 [地名/地圖網址]\n"
            "🗑️ 刪除 [編號]\n"
            "📝 註解 [編號] [說明]\n"
            "📋 地點 或 清單：顯示排序後地點\n"
            "❌ 清空：刪除所有地點（需再次確認）\n"
            "📚 修改註解：[編號] [原內容] [新內容]"
        )

    # 批次新增地點
    elif any(msg.startswith(k) or msg.startswith(f"{k}\n") for k in ADD_ALIASES):
        lines = [line.strip() for line in msg.splitlines() if line.strip()]
        if any(lines[0].startswith(k) for k in ADD_ALIASES):
            lines = lines[1:]

        added, duplicate, failed = [], [], []
        existing_names = [doc["name"] for doc in collection.find({"user_id": user_id})]

        for line in lines:
            name = resolve_place_name(line)
            if not name or name.startswith("⚠️"):
                failed.append(line)
                continue
            name = clean_place_title(name)
            if name in existing_names:
                duplicate.append(name)
                continue
            try:
                geo = gmaps.geocode(name)
                if geo:
                    lat = geo[0]["geometry"]["location"]["lat"]
                    lng = geo[0]["geometry"]["location"]["lng"]
                    collection.insert_one({
                        "user_id": user_id,
                        "name": name,
                        "lat": lat,
                        "lng": lng
                    })
                else:
                    collection.insert_one({"user_id": user_id, "name": name})
                added.append(name)
                existing_names.append(name)
            except Exception as e:
                logging.warning(f"❌ 新增地點錯誤：{e}")
                failed.append(line)

        parts = []
        if added: parts.append("✅ 已新增地點：\n- " + "\n- ".join(added))
        if duplicate: parts.append("⛔️ 重複地點（已略過）：\n- " + "\n- ".join(duplicate))
        if failed: parts.append("⚠️ 無法解析：\n- " + "\n- ".join(failed))
        reply = "\n\n".join(parts) if parts else "⚠️ 沒有成功加入任何地點"

    # 回覆訊息
    if reply:
        try:
            api_instance.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        except Exception as e:
            logging.warning(f"❌ 回覆訊息錯誤：{e}")

# ping
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
