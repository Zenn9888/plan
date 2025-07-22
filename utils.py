import googlemaps
import requests
from linebot.models import FlexSendMessage
import json

def get_coordinates(query, gmaps):
    try:
        results = gmaps.geocode(query)
        if results:
            location = results[0]["geometry"]["location"]
            return {"lat": location["lat"], "lng": location["lng"]}
    except:
        return None

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

def create_static_map_url(locations, api_key):
    markers = "&".join([f"markers={lat},{lng}" for _, lat, lng in locations])
    return f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&{markers}&key={api_key}"

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

def show_location_list(user_id, collection):
    docs = list(collection.find({"user_id": user_id}))
    if not docs:
        return "目前尚未加入任何地點。"
    reply = "📍 目前地點清單：\n"
    for i, doc in enumerate(docs, 1):
        reply += f"{i}. {doc['name']}\n"
    return reply

def clear_locations(user_id, collection):
    collection.delete_many({"user_id": user_id})
    return "✅ 所有地點已清空。"

def add_location(user_id, name, lat, lng, collection):
    collection.insert_one({"user_id": user_id, "name": name, "lat": lat, "lng": lng})
    return f"✅ 已加入地點：{name}"

def create_flex_message():
    with open("flex_message_template.json", "r", encoding="utf-8") as f:
        content = json.load(f)
    return FlexSendMessage(alt_text="指令選單", contents=content)
