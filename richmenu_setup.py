

import os
from linebot.v3.messaging import MessagingApi, Configuration, ApiClient
from linebot.v3.messaging.models import (
    RichMenuRequest, RichMenuArea, RichMenuBounds, MessageAction
)

# ✅ 讀取環境變數
CHANNEL_ACCESS_TOKEN = "vuYcV9fNuaG0ExvnAnhQZrBRXWIuxnb7Gjt/w6PYVKX4pEgJP2+70Ly4aNXNDIYsJoP3o9N+nkEaITPPJ3DVOOBRIBJqJm7RGe52cOqVKoIIB4rQOWkA11CXSNrP3n9jMWAwFJwZZbuStiUs5pyDXwdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET="ba92fcbb6de3cac0a7fb129adb705653"

# ✅ 設定 LINE Messaging API 客戶端
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

def setup_rich_menu_once():
    with ApiClient(configuration) as api_client:
        api_instance = MessagingApi(api_client)
        
        # ✅ 正確取得 Rich Menu 列表的方法
        menus = api_instance.get_rich_menu_list()
        if menus.richmenus:
            print("✔️ RichMenu 已存在，跳過建立。")
            return

        # ✅ 建立新的 RichMenu
        req = RichMenuRequest(
            size={"width": 2500, "height": 843},
            selected=True,
            name="功能選單",
            chat_bar_text="打開選單",
            areas=[
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                    action=MessageAction(label="新增地點", text="新增地點 台北101")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=834, y=0, width=833, height=843),
                    action=MessageAction(label="顯示地點", text="地點清單")
                ),
                RichMenuArea(
                    bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                    action=MessageAction(label="排序路線", text="排序路線")
                )
            ]
        )

        rich_menu_id = api_instance.create_rich_menu(rich_menu_request=req).rich_menu_id

        with open("static/menu.png", "rb") as f:
            api_instance.set_rich_menu_image(rich_menu_id, "image/png", f)

        api_instance.set_default_rich_menu(rich_menu_id)
        print("✅ RichMenu 建立完成並設為預設選單")

if __name__ == "__main__":
    setup_rich_menu_once()
