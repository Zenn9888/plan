import os, re, requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from urllib.parse import quote
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

client = MongoClient(MONGO_URI)
db = client["line_bot"]
locations = db["locations"]

ADD_PATTERNS = ["新增", "加入", "地點", r"\+ ?", "add", "加", "增"]
DEL_PATTERNS = ["刪除", "移除", "delete", "del"]

def extract_location_from_url(text):
    match = re.search(r'https://maps\.app\.goo\.gl/\S+', text)
    if not match:
        return None
    try:
        resolved = requests.get(match.group(0), allow_redirects=True)
        loc_match = re.search(r'/place/([^/]+)', resolved.url)
        if loc_match:
            return loc_match.group(1).replace('+', ' ')
    except:
        pass
    return None

def geocode(place):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={quote(place)}&key={GOOGLE_API_KEY}"
    res = requests.get(url).json()
    if res["status"] == "OK":
        loc = res["results"][0]["geometry"]["location"]
        return {
            "name": res["results"][0]["formatted_address"],
            "lat": loc["lat"],
            "lng": loc["lng"]
        }
    return None

def get_directions(loc_list):
    if len(loc_list) < 2:
        return None
    origin = f"{loc_list[0]['lat']},{loc_list[0]['lng']}"
    destination = f"{loc_list[-1]['lat']},{loc_list[-1]['lng']}"
    waypoints = "|".join([f"{loc['lat']},{loc['lng']}" for loc in loc_list[1:-1]])
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}&travelmode=driving"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    # 處理刪除指令
    for p in DEL_PATTERNS:
        if re.match(p, msg, re.IGNORECASE):
            keyword = re.sub(p, "", msg, flags=re.IGNORECASE).strip()
            locations.delete_many({"user": user_id, "name": {"$regex": keyword}})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已刪除包含「{keyword}」的地點"))
            return

    # 處理 Google Maps 分享連結
    extracted = extract_location_from_url(msg)
    if extracted:
        info = geocode(extracted)
        if info:
            info["user"] = user_id
            locations.insert_one(info)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已新增地點：{info['name']}"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="無法從網址解析地點"))
        return

    # 處理新增地點
    for p in ADD_PATTERNS:
        if re.match(p, msg, re.IGNORECASE):
            keyword = re.sub(p, "", msg, flags=re.IGNORECASE).strip()
            info = geocode(keyword)
            if info:
                info["user"] = user_id
                locations.insert_one(info)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已新增地點：{info['name']}"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="找不到該地點"))
            return

    # 處理排序
    if "排序" in msg or "路線" in msg:
        user_locs = list(locations.find({"user": user_id}))
        if len(user_locs) < 2:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請先新增至少兩個地點"))
            return
        url = get_directions(user_locs)
        if url:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"📍 建議路線：\n{url}"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="無法生成路線"))
        return

    # 列出地點
    if "查看" in msg or "地點列表" in msg:
        user_locs = list(locations.find({"user": user_id}))
        if not user_locs:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="你還沒新增地點"))
            return
        reply = "\n".join([f"{i+1}. {loc['name']}" for i, loc in enumerate(user_locs)])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="📍 已新增地點：\n" + reply))
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入：新增地點 或 路線"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
