# === 開頭載入與初始化 ===
import os, re, requests, logging
from urllib.parse import unquote
from dotenv import load_dotenv
from flask import Flask, request, abort
from pymongo import MongoClient
import googlemaps
import datetime
import pytz
import urllib.parse
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
CWB_API_KEY = os.getenv("CWB_API_KEY")
logging.info(f"✅ CWB_API_KEY 讀到：{CWB_API_KEY}")
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
def get_weather(location_name):
    try:
        encoded_location = urllib.parse.quote(location_name)
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={CWB_API_KEY}&locationName={encoded_location}"
        res = requests.get(url).json()
        location = res["records"]["location"][0]

        name = location["locationName"]
        elements = {e["elementName"]: e["time"] for e in location["weatherElement"]}

        def format_weather(index):
            wx = elements["Wx"][index]["parameter"]["parameterName"]
            pop = elements["PoP"][index]["parameter"]["parameterName"]
            min_t = elements["MinT"][index]["parameter"]["parameterName"]
            max_t = elements["MaxT"][index]["parameter"]["parameterName"]
            return f"📍 {name}\n☀️ {wx}　🌡️ {min_t}°C / {max_t}°C　🌧️ 降雨機率 {pop}%"

        today = format_weather(0)
        tomorrow = format_weather(2) if len(elements["Wx"]) > 2 else None

        return f"{today}\n\n{tomorrow}" if tomorrow else today
    except Exception as e:
        logging.warning(f"❌ 天氣查詢失敗：{e}")
        return "⚠️ 查詢天氣失敗，請確認地名是否正確。"

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
    # 顯示清單
    if any(k in msg for k in ["清單", "地點"]):
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
            lines = []
            for i, item in enumerate(items):
                name = clean_place_title(item["name"])
                lat, lng = item.get("lat"), item.get("lng")
                nav_link = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}" if lat and lng else ""
                line = f"{i+1}. {name}"
                if item.get("comment"):
                    line += f"（{item['comment']}）"
                if nav_link:
                    line += f"\n👉 [導航]({nav_link})"
                lines.append(line)
            reply = "📍 地點清單：\n" + "\n\n".join(lines)


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

    # === 查詢天氣 ===
    elif msg.strip() == "天氣":
        if not items:
            reply = "📭 尚未新增任何地點"
        else:
            weather_list = []
            for i, loc in enumerate(items):
                lat = loc.get("lat")
                lng = loc.get("lng")
                if lat and lng:
                    try:
                        geo_result = gmaps.reverse_geocode((lat, lng), language="zh-TW")
                        district_name = None
                        town_name = None  # 行政區 level 3
                        area_name = None  # level 2，例如「台東市」「壽豐鄉」
                        for comp in geo_result[0]["address_components"]:
                            if "administrative_area_level_3" in comp["types"]:
                                town_name = comp["long_name"]
                            elif "administrative_area_level_2" in comp["types"]:
                                area_name = comp["long_name"]

                        # 優先使用鄉鎮區，再 fallback 到縣市（level 2）
                        district_name = town_name or area_name
                        # 自訂 fallback 對照（可擴充）
                        fallback_map = {
                            # 花蓮縣
                            "花蓮市": "花蓮縣花蓮市",
                            "新城鄉": "花蓮縣新城鄉",
                            "秀林鄉": "花蓮縣秀林鄉",
                            "吉安鄉": "花蓮縣吉安鄉",
                            "壽豐鄉": "花蓮縣壽豐鄉",
                            "鳳林鎮": "花蓮縣鳳林鎮",
                            "光復鄉": "花蓮縣光復鄉",
                            "豐濱鄉": "花蓮縣豐濱鄉",
                            "瑞穗鄉": "花蓮縣瑞穗鄉",
                            "萬榮鄉": "花蓮縣萬榮鄉",
                            "玉里鎮": "花蓮縣玉里鎮",
                            "卓溪鄉": "花蓮縣卓溪鄉",
                            "富里鄉": "花蓮縣富里鄉",
                        
                            # 台東縣（注意「臺」非「台」）
                            "台東市": "臺東縣臺東市",
                            "成功鎮": "臺東縣成功鎮",
                            "關山鎮": "臺東縣關山鎮",
                            "長濱鄉": "臺東縣長濱鄉",
                            "池上鄉": "臺東縣池上鄉",
                            "東河鄉": "臺東縣東河鄉",
                            "鹿野鄉": "臺東縣鹿野鄉",
                            "卑南鄉": "臺東縣卑南鄉",
                            "大武鄉": "臺東縣大武鄉",
                            "太麻里鄉": "臺東縣太麻里鄉",
                            "綠島鄉": "臺東縣綠島鄉",
                            "延平鄉": "臺東縣延平鄉",
                            "金峰鄉": "臺東縣金峰鄉",
                            "海端鄉": "臺東縣海端鄉",
                            "達仁鄉": "臺東縣達仁鄉",
                            "蘭嶼鄉": "臺東縣蘭嶼鄉"
                        }


# 若目前 district_name 是錯的細分名，則使用對照表修正
                        if district_name in fallback_map:
                            district_name = fallback_map[district_name]

                        if not district_name:
                            weather_list.append(f"⚠️ {i+1}. {loc['name']} 查無行政區")
                            continue

                        title = clean_place_title(loc["name"])
                        rain_1hr, temp_1hr = get_rain_temp_1hr_by_location(district_name)
                        rain_1hr_txt = f"🌧️ 1 小時降雨 {rain_1hr}%" if rain_1hr else "🌧️ 降雨資料缺失"
                        temp_txt = f"🌡️ 溫度 {temp_1hr}°C" if temp_1hr else "🌡️ 溫度資料缺失"

                        forecast = get_weather_by_district(district_name)
                        if forecast:
                            weather_list.append(
                                f"📌 {i+1}. {title}（{district_name}）\n🔍 使用行政區：{district_name}\n{rain_1hr_txt}　{temp_txt}\n{forecast}"
                            )
                        else:
                            f"⚠️ {i+1}. {title}（{district_name}） 查無天氣預報\n🔍 使用行政區：{district_name}"

                    except Exception as e:
                        logging.warning(f"❌ 天氣查詢錯誤：{e}")
                        weather_list.append(f"⚠️ {i+1}. {loc['name']} 查詢失敗")
                else:
                    weather_list.append(f"⚠️ {i+1}. {loc['name']} 缺少經緯度")

            reply = "\n\n".join(weather_list)




    # 回覆訊息
    if reply:
        try:
            api_instance.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        except Exception as e:
            logging.warning(f"❌ 回覆訊息錯誤：{e}")
def get_weather_by_district(district_name):
    """查詢今明天氣預報（F-D0047-091）"""
    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091"
        params = {
            "Authorization": CWB_API_KEY,
            "format": "JSON",
            "locationName": district_name
        }

        res = requests.get(url, params=params, timeout=5)
        logging.debug(f"🌐 [F-D0047-091 回傳內容] {res.text[:100]}")  # 顯示前 100 字預覽

        try:
            data = res.json()
        except Exception as e:
            logging.error(f"❌ JSON 解碼失敗：{e}")
            logging.warning(f"⚠️ 原始回傳：{res.text}")
            return None

        locations = data.get("records", {}).get("locations", [])
        if not locations:
            return None

        location = locations[0]["location"][0]
        wx = location["weatherElement"][0]["time"]
        min_t = location["weatherElement"][8]["time"]
        max_t = location["weatherElement"][12]["time"]
        pop = location["weatherElement"][1]["time"]

        result = []
        for i in range(2):  # 今明兩天白天
            label = "今天" if i == 0 else "明天"
            t_desc = wx[i]["elementValue"][0]["value"]
            t_min = min_t[i]["elementValue"][0]["value"]
            t_max = max_t[i]["elementValue"][0]["value"]
            t_pop = pop[i]["elementValue"][0]["value"]
            result.append(
                f"{label} ☀️ {t_desc}　🌡️ {t_min}°C / {t_max}°C　🌧️ 降雨機率 {t_pop}%"
            )
        return "\n".join(result)

    except Exception as e:
        logging.warning(f"❌ 天氣 API 錯誤：{e}")
        return None


def get_rain_temp_1hr_by_location(district_name):
    """查詢 1 小時降雨機率與即時溫度（F-D0047-093）"""
    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-093"
        res = requests.get(url, params={
            "Authorization": CWB_API_KEY,
            "format": "JSON",
            "locationName": district_name
        }, timeout=5)

        logging.debug(f"🌐 [F-D0047-093 回傳內容] {res.text[:100]}")  # 顯示預覽

        try:
            data = res.json()
        except Exception as e:
            logging.error(f"❌ JSON 解碼失敗：{e}")
            logging.warning(f"⚠️ 原始回傳：{res.text}")
            return None, None

        locations = data.get("records", {}).get("locations", [])
        if not locations:
            return None, None

        location = locations[0]["location"][0]
        rain = location["weatherElement"][0]["time"][0]["elementValue"][0]["value"]  # 降雨機率
        temp = location["weatherElement"][1]["time"][0]["elementValue"][0]["value"]  # 溫度 T

        return rain, temp
    except Exception as e:
        logging.warning(f"❌ 1 小時天氣查詢錯誤：{e}")
        return None, None




# ping
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
