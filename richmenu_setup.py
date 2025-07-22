import os
import requests
from dotenv import load_dotenv
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi

from linebot.v3.messaging.models.rich_menu_request import RichMenuRequest
from linebot.v3.messaging.models.rich_menu_area import RichMenuArea
from linebot.v3.messaging.models.rich_menu_bounds import RichMenuBounds
from linebot.v3.messaging.models.rich_menu_size import RichMenuSize
from linebot.v3.messaging.models.message_action import MessageAction

# ✅ 載入 .env 設定
load_dotenv()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or "Hele0z6vAK/3ZN0HlefQAb+lx57F/mwM/B/Xue97aS8qB5ZD9IrcBhDpXpIEZ3DDJoP3o9N+nkEaITPPJ3DVOOBRIBJqJm7RGe52cOqVKoIpAVFUfWPMGs3H0lvv87irnFDsA4vmI45XDJtgJacflAdB04t89/1O/w1cDnyilFU="


image_path = "./static/menu.png"

# ✅ 設定 Messaging API
config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
api_instance = MessagingApi(ApiClient(config))

def upload_richmenu_image(rich_menu_id, image_path):
    with open(image_path, 'rb') as f:
        headers = {
            'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}',
            'Content-Type': 'image/png'
        }
        url = f'https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content'
        res = requests.post(url, headers=headers, data=f)
        if res.status_code == 200:
            print("✅ 圖片上傳成功")
            return True
        else:
            print(f"❌ 圖片上傳失敗: {res.status_code} - \n{res.text}")
            return False

def delete_all_richmenus():
    menus = api_instance.get_rich_menu_list()
    for m in menus.richmenus:
        api_instance.delete_rich_menu(m.rich_menu_id)
        print(f"🗑️ 刪除 RichMenu: {m.rich_menu_id}")

def setup_rich_menu_once():
    delete_all_richmenus()

    rich_menu = RichMenuRequest(
        size=RichMenuSize(width=2500, height=843),
        selected=True,
        name="MainMenu",
        chat_bar_text="🧭 功能選單",
        areas=[
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                action=MessageAction(text="📝 新增地點")
            ),
            RichMenuArea(
                bounds=RichMenuBounds(x=834, y=0, width=833, height=843),
                action=MessageAction(text="📍 地點清單")
            ),
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                action=MessageAction(text="🚗 排序路線")
            )
        ]
    )

    res = api_instance.create_rich_menu(rich_menu)
    rich_menu_id = res.rich_menu_id
    print(f"✅ RichMenu 已建立，ID: {rich_menu_id}")

    success = upload_richmenu_image(rich_menu_id, image_path)

    if success:
        api_instance.set_default_rich_menu(rich_menu_id)
        print("✅ 已設為預設 RichMenu")
    else:
        print("⚠️ 未設為預設選單，請確認圖片上傳成功")

if __name__ == "__main__":
    setup_rich_menu_once()
