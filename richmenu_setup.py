from linebot import LineBotApi
from linebot.models import RichMenu, RichMenuArea, RichMenuBounds, MessageAction
import os

def setup_rich_menu(token):
    line_bot_api = LineBotApi(token)

    rich_menu = RichMenu(
        size=RichMenu.RichMenuSize(width=2500, height=843),
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

    # 建立 RichMenu 並上傳圖片
    rich_menu_id = line_bot_api.create_rich_menu(rich_menu)
    with open("static/menu.png", "rb") as f:
        line_bot_api.set_rich_menu_image(rich_menu_id, "image/png", f)

    # 設定為預設 Rich Menu
    line_bot_api.set_default_rich_menu(rich_menu_id)
