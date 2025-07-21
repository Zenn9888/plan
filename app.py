from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os, re, requests
from urllib.parse import unquote
from pymongo import MongoClient

# === 環境變數 ===
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")
MONGO_URI = os.environ.get("MONGO_URI")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# === MongoDB ===
client = MongoClient(MONGO_URI)
db = client["line_bot"]
locations = db["locations"]
locations.create_index("user")

app = Flask(__name__)

# === 工具：關鍵詞判斷 ===
def is_add_command(text):
    return re.match(r'^(新增|加入|add|地點|加|增|\+\s?)', text.strip(), re.IGNORECASE)

def is_delete_command(text):
    return re.match(r'^(刪除|移除|delete|del|\-)', text.strip(), re.IGNORECASE)

def extract_place(text):
    if is_add_command(text):
        return re.sub(r'^(新增|加入|add|地點|加|增|\+)\s*', '', text.strip(), flags=re.IGNORECASE)
    elif is_delete_command(text):
        return re.sub(r'^(刪除|移除|delete|del|\-)\s*', '', text.strip(), flags=re.IGNORECASE)
    return text.strip()

# === 工具：從 Google Maps 短網址解析地點名稱 ===
def resolve_place_from_url(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=5)
        title_match = re.search(r'<title>(.*?) - Google 地圖</title>', r.text)
        return title_match.group(1).strip() if title_match else None
    except:
        return None

# === 工具：取得經緯度 ===
def geocode_place(place):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={place}&key={GOOGLE_MAPS_API_KEY}"
    r = requests.get(url)
    data = r.json()
    if data["status"] == "OK":
        result = data["results"][0]
        name = result["formatted_address"]
        lat = result["geometry"]["location"]["lat"]
        lng = result["geometry"]["location"]["lng"]
        return {"name": name, "lat": lat, "lng": lng}
    return None

# === 工具：取得排序路線 ===
def get_sorted_route(locations_list):
    if len(locations_list) < 2:
        return None, "請至少加入兩個地點以進行排序。"
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    origin = f"{locations_list[0]['lat']},{locations_list[0]['lng']}"
    destination = f"{locations_list[-1]['lat']},{locations_list[-1]['lng']}"
    waypoints = "|".join([f"{loc['lat']},{loc['lng']}" for loc in locations_list[1:-1]])

    params = {
        "origin": origin,
        "destination": destination,
        "waypoints": f"optimize:true|{waypoints}" if waypoints else "",
        "key": GOOGLE_MAPS_API_KEY
    }

    r = requests.get(base_url, params=params)
    result = r.json()
    if result["status"] != "OK":
        return None, "路線排序失敗，請稍後再試。"

    order = result["routes"][0]["waypoint_order"]
    sorted_locs = [locations_list[0]] + [locations_list[i + 1] for i in order] + [locations_list[-1]]
    return sorted_locs, None

# === Line Webhook ===
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# === 文字處理 ===
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # 將分享網址轉為地點名稱
    if "maps.app.goo.gl" in text:
        resolved = resolve_place_from_url(text)
        if resolved:
            text = "新增 " + resolved
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 無法解析 Google Maps 網址"))
            return

    # 新增地點
    if is_add_command(text):
        place_name = extract_place(text)
        geo = geocode_place(place_name)
        if geo:
            geo["user"] = user_id
            locations.insert_one(geo)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"✅ 已新增地點：{geo['name']}"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 找不到該地點"))
        return

    # 刪除地點
    if is_delete_command(text):
        place_name = extract_place(text)
        result = locations.delete_many({"user": user_id, "name": {"$regex": place_name}})
        if result.deleted_count > 0:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🗑️ 已刪除 {result.deleted_count} 筆地點"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ 找不到要刪除的地點"))
        return

    # 查詢地點列表
    if text in ["查詢", "列表", "地點", "我的地點"]:
        user_locs = list(locations.find({"user": user_id}))
        if not user_locs:
            reply = "📭 尚未儲存任何地點"
        else:
            reply = "📍 目前儲存地點：\n" + "\n".join([f"{i+1}. {loc['name']}" for i, loc in enumerate(user_locs)])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 排序
    if text in ["排序", "路線", "導航"]:
        user_locs = list(locations.find({"user": user_id}))
        sorted_locs, err = get_sorted_route(user_locs)
        if err:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ " + err))
            return

        reply = "🧭 建議路線排序：\n" + "\n".join([f"{i+1}. {loc['name']}" for i, loc in enumerate(sorted_locs)])
        # 動態地圖網址
        map_url = "https://www.google.com/maps/dir/" + "/".join(
            [f"{loc['lat']},{loc['lng']}" for loc in sorted_locs]
        )
        reply += f"\n\n🗺️ [動態地圖連結]({map_url})"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 不明指令
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🤖 指令無法辨識，請輸入：新增地點、刪除地點、查詢、排序"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
