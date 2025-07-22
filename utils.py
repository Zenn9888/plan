import requests
import googlemaps
from pymongo.collection import Collection
from linebot.v3.messaging.models.flex_message import FlexMessage
from linebot.v3.messaging.models.bubble_container import BubbleContainer
from linebot.v3.messaging.models.text_component import TextComponent
# ✅ 查地址座標
def get_coordinates(query, gmaps):
    try:
        results = gmaps.geocode(query)
        if results:
            location = results[0]["geometry"]["location"]
            return {"lat": location["lat"], "lng": location["lng"]}
    except:
        return None

# ✅ Google Maps 多點排序連結
def get_sorted_route_url(locations, api_key):
    waypoints = "|".join([f"{lat},{lng}" for _, lat, lng in locations[1:-1]])
    origin = f"{locations[0][1]},{locations[0][2]}"
    dest = f"{locations[-1][1]},{locations[-1][2]}"
    url = (
        f"https://www.google.com/maps/dir/?api=1"
        f"&origin={origin}"
        f"&destination={dest}"
        f"&waypoints={waypoints}"
        f"&travelmode=driving"
    )
    return url

# ✅ 靜態地圖 URL（選用）
def create_static_map_url(locations, api_key):
    markers = "&".join([f"markers={lat},{lng}" for _, lat, lng in locations])
    return f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&{markers}&key={api_key}"

# ✅ 解析短網址
def extract_location_from_url(short_url, gmaps):
    try:
        res = requests.get(short_url, allow_redirects=True)
        if res.status_code == 200 and "place" in res.url:
            place_name = res.url.split("/place/")[1].split("/")[0]
            return {
                "name": place_name.replace("+", " "),
                **get_coordinates(place_name.replace("+", " "), gmaps)
            }
    except:
        return None

# ✅ 顯示目前所有地點
def show_location_list(user_id, collection: Collection):
    docs = list(collection.find({"user_id": user_id}))
    if not docs:
        return "目前尚未加入任何地點。"
    reply = "📍 目前地點清單：\n"
    for i, doc in enumerate(docs, 1):
        reply += f"{i}. {doc['name']}\n"
    return reply

# ✅ 清空所有地點
def clear_locations(user_id, collection: Collection):
    collection.delete_many({"user_id": user_id})
    return "✅ 所有地點已清空。"

# ✅ 新增一個地點
def add_location(user_id, name, lat, lng, collection: Collection):
    collection.insert_one({"user_id": user_id, "name": name, "lat": lat, "lng": lng})
    return f"✅ 已加入地點：{name}"

# ✅ Flex Message 小卡指令提示
def create_flex_message():
    bubble = BubbleContainer(
        body=TextComponent(
            text="請使用以下指令：\n\n✅ 新增地點 台北101\n📍 地點清單\n🚗 排序路線\n🗑️ 清空所有地點",
            wrap=True
        )
    )
    return FlexMessage(
        alt_text="功能選單",
        contents=bubble
    )
