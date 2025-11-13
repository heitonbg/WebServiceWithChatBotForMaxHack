import asyncio
import logging
import threading
import uvicorn
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

from app.api import app as api_app
from app.models import init_db

logging.basicConfig(level=logging.INFO)

def run_api():
    uvicorn.run(api_app, host="0.0.0.0", port=8000, log_level="info")

def run_bot():
    from app.bot_impl import main
    main() 

if __name__ == "__main__":
    init_db()

    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()

    logging.info("🚀 Starting TaskBot with API...")
    run_bot()