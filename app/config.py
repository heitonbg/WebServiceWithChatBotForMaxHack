import os
from dotenv import load_dotenv
from pathlib import Path

# Находим корневую директорию проекта
# Поднимаемся на 2 уровня вверх от текущего файла (app/config.py -> корень)
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent  # идём вверх 2 раза: app/config.py -> app/ -> корень

# Путь к .env файлу
env_path = project_root / '.env'

# Загружаем .env файл
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print(f"✅ .env загружен из: {env_path}")
else:
    # Пробуем загрузить из текущей директории
    load_dotenv()
    print(f"⚠️ .env не найден в {env_path}, загружаем из текущей директории: {os.getcwd()}")

MAX_BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
WEB_APP_URL = os.getenv('WEB_APP_URL', "https://webtomax.vercel.app")

if not MAX_BOT_TOKEN:
    # Выводим отладочную информацию
    print(f"❌ MAX_BOT_TOKEN не найден!")
    print(f"   Искали .env в: {env_path}")
    print(f"   Файл существует: {env_path.exists()}")
    print(f"   Текущая директория: {os.getcwd()}")
    print(f"   Все переменные окружения: {[k for k in os.environ.keys() if 'TOKEN' in k or 'BOT' in k]}")
    
    raise ValueError("❌ MAX_BOT_TOKEN не найден в .env файле!")

print(f"✅ MAX_BOT_TOKEN загружен (первые 20 символов: {MAX_BOT_TOKEN[:20]}...)")