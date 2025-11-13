import os
from dotenv import load_dotenv

load_dotenv()

MAX_BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
WEB_APP_URL = os.getenv('WEB_APP_URL', "https://webtomax.vercel.app")

if not MAX_BOT_TOKEN:
    raise ValueError("❌ MAX_BOT_TOKEN не найден в .env файле!")
