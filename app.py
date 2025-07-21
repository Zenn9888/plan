import os
import re
import requests
import googlemaps
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import *
from pymongo import MongoClient
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()
app = Flask(__name__)
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
MONGO_URI = os.getenv("MONGO_URI")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["line_bot"]
locations_col = db["locations"]

# 轉換 Google Maps 短網址為地址
def resolve_gmaps_url(url):
    try:
        response = requests.get(url, allow_redirects=True, timeout=10)
        return response.url
    except:
        return None

# Flex 小卡提示
def send_flex_guide(reply_token):
    flex = {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://maps.gstatic.com/tactile/basepage/pegman_sherlock.png",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "地點排序小幫手", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "請輸入：\n🔹 新增 台北101\n🔹 刪除 XX\n🔹 排序地點", "wrap": True, "margin": "md", "size": "sm"}
            ]
        }
    }
    line_bot_api.reply_message(reply_token, FlexSendMessage("功能說明", flex))

@app.route("/", methods=['GET'])
def home():
    return "Line Bot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except Exception as e:
        abort(400)
    return 'OK'

def extract_location_from_text(text):
    url_match = re.search(r'https://maps\.app\.goo\.gl/\S+', text)
    if url_match:
        final_url = resolve_gmaps_url(url_match.group())
        if final_url:
            q = parse_qs(urlparse(final_url).query)
            return final_url.split('/place/')[1].split('/')[0].replace('+', ' ')
    return text.strip().split(maxsplit=1)[-1]

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    if any(key in msg for key in ["新增", "加入", "+", "加", "增", "地點", "add"]):
        name = extract_location_from_text(msg)
        try:
            geocode_result = gmaps.geocode(name)
            if not geocode_result:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 找不到該地點"))
                return
            loc = geocode_result[0]["geometry"]["location"]
            address = geocode_result[0]["formatted_address"]
            locations_col.insert_one({"user": user_id, "name": name, "address": address, "lat": loc["lat"], "lng": loc["lng"]})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已新增：{name}"))
        except Exception:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 地點加入失敗"))
        return

    if any(key in msg for key in ["刪除", "移除", "delete", "del", "-", "刪", "移"]):
        keyword = msg.strip().split(maxsplit=1)[-1]
        result = locations_col.delete_many({"user": user_id, "name": {"$regex": keyword}})
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🗑️ 已刪除 {result.deleted_count} 筆地點"))
        return

    if "排序" in msg or "路線" in msg:
        records = list(locations_col.find({"user": user_id}))
        if len(records) < 2:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 請先新增兩個以上地點"))
            return
        waypoints = [(r["lat"], r["lng"]) for r in records]
        names = [r["name"] for r in records]
        try:
            route = gmaps.directions(origin=waypoints[0],
                                     destination=waypoints[-1],
                                     waypoints=waypoints[1:-1],
                                     mode="driving")[0]
            steps = [leg["start_address"] for leg in route["legs"]] + [route["legs"][-1]["end_address"]]
            reply = "📍 最佳路線排序：\n" + "\n".join([f"{i+1}. {names[i]}" for i in range(len(names))])
            map_url = f"https://www.google.com/maps/dir/" + "/".join([f'{lat},{lng}' for lat, lng in waypoints])
            reply += f"\n\n🗺️ 路線圖：{map_url}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 路線規劃失敗"))
        return

    if msg in ["help","說明", "使用說明"]:
        send_flex_guide(event.reply_token)
    

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
