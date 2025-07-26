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

def get_weather_by_district(district_name):
    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091"
        params = {
            "Authorization": CWB_API_KEY,
            "format": "JSON",
            "locationName": district_name
        }
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
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
    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-093"
        res = requests.get(url, params={
            "Authorization": CWB_API_KEY,
            "locationName": district_name
        }, timeout=5)
        data = res.json()
        locations = data.get("records", {}).get("locations", [])
        if not locations:
            return None, None
        location = locations[0]["location"][0]

        rain = location["weatherElement"][0]["time"][0]["elementValue"][0]["value"]
        temp = location["weatherElement"][1]["time"][0]["elementValue"][0]["value"]

        return rain, temp
    except Exception as e:
        logging.warning(f"❌ 1 小時天氣查詢錯誤：{e}")
        return None, None

# ☁️ 天氣查詢（整合經緯度 → 行政區 → 天氣 + 降雨 + 即時溫度）
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    reply = ""

    items = list(collection.find({"user_id": user_id}).sort("lat", 1))

    if msg.strip() == "天氣":
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
                        town_name = None
                        area_name = None

                        for comp in geo_result[0]["address_components"]:
                            if "administrative_area_level_3" in comp["types"]:
                                town_name = comp["long_name"]
                            elif "administrative_area_level_2" in comp["types"]:
                                area_name = comp["long_name"]

                        district_name = town_name or area_name

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
                                f"📌 {i+1}. {title}（{district_name}）\n{rain_1hr_txt}　{temp_txt}\n{forecast}"
                            )
                        else:
                            weather_list.append(f"⚠️ {i+1}. {title}（{district_name}） 查無天氣預報")

                    except Exception as e:
                        logging.warning(f"❌ 天氣查詢錯誤：{e}")
                        weather_list.append(f"⚠️ {i+1}. {loc['name']} 查詢失敗")
                else:
                    weather_list.append(f"⚠️ {i+1}. {loc['name']} 缺少經緯度")

            reply = "\n\n".join(weather_list)

    if reply:
        try:
            api_instance.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply)])
            )
        except Exception as e:
            logging.warning(f"❌ 回覆訊息錯誤：{e}")
