# gigachat_client.py
import json
import sys
import requests
import logging
import os
import uuid
import time
from typing import List, Optional
from dotenv import load_dotenv
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
load_dotenv()

class GigaChatClient:
    def __init__(self):
        # Authorization key - это уже готовый Base64 ключ для Basic аутентификации
        self.auth_key = os.getenv('GIGACHAT_AUTH_KEY') or os.getenv('GIGACHAT_CLIENT_SECRET')
        self.client_id = os.getenv('GIGACHAT_CLIENT_ID')
        self.access_token = None
        self.token_expires_at = 0
        self.token_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        self.api_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        
        if not self.auth_key:
            logging.error("❌ GIGACHAT_AUTH_KEY not set in .env")
        else:
            logging.info(f"✅ Authorization key loaded (length: {len(self.auth_key)})")

    def get_access_token(self) -> Optional[str]:
        try:
            if not self.auth_key:
                logging.error("❌ Authorization key is missing")
                return None

            logging.info("🔄 Requesting new GigaChat access token...")
            
            payload = {'scope': 'GIGACHAT_API_PERS'}
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
                'RqUID': str(uuid.uuid4()),
                'Authorization': f'Basic {self.auth_key}'  # Здесь直接用 auth_key
            }

            response = requests.post(
                self.token_url, 
                headers=headers, 
                data=payload, 
                verify=False,  # Для тестов, в продакшене используй verify=True
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get('access_token')
                expires_in = result.get('expires_in', 1800)
                self.token_expires_at = time.time() + expires_in - 120  # Запас 2 минуты
                
                logging.info(f"✅ GigaChat token obtained, expires in {expires_in} seconds")
                logging.info(f"   Token preview: {self.access_token[:20]}...")
                return self.access_token
            else:
                logging.error(f"❌ GigaChat token error: {response.status_code}")
                logging.error(f"   Response: {response.text}")
                return None

        except Exception as e:
            logging.error(f"❌ GigaChat token request failed: {e}")
            return None

    def is_token_valid(self) -> bool:
        if not self.access_token:
            return False
        return time.time() < self.token_expires_at

    def ensure_valid_token(self) -> bool:
        if self.is_token_valid():
            return True
        
        logging.info("🔄 Token expired or invalid, refreshing...")
        return self.get_access_token() is not None

    def decompose_task(self, task_title: str) -> Optional[List[str]]:
        """Разложить задачу на подзадачи с помощью GigaChat"""
        try:
            if not self.ensure_valid_token():
                logging.warning("❌ No valid GigaChat token available")
                return None

            prompt = f"""Разложи задачу "{task_title}" на 3-5 конкретных практических шагов для выполнения.

ТРЕБОВАНИЯ К ФОРМАТУ:
- Каждый шаг должен быть кратким и конкретным
- Начинать с глагола действия (купить, найти, сделать, подготовить и т.д.)
- Максимальная длина шага - 7-8 слов
- Шаги должны быть последовательными и логичными

ФОРМАТ СТРОГО:
1. Конкретный шаг 1
2. Конкретный шаг 2  
3. Конкретный шаг 3
4. Конкретный шаг 4
5. Конкретный шаг 5

Пример для "сделать маме подарок":
1. Узнать предпочтения и интересы мамы
2. Выбрать тип подарка по бюджету
3. Найти подходящий магазин или сервис
4. Купить или создать подарок
5. Красиво упаковать и подписать

Теперь разложи: "{task_title}"""

            payload = {
                "model": "GigaChat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300
            }

            headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.access_token}'
            }

            response = requests.post(
                self.api_url, 
                headers=headers, 
                json=payload, 
                verify=False,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                steps = self._parse_response(content)
                
                if steps:
                    logging.info(f"✅ GigaChat decomposition successful: {len(steps)} steps")
                    return steps
                else:
                    logging.warning(f"❌ Could not parse GigaChat response")
                    logging.debug(f"   Response: {content}")
                    return None
            elif response.status_code == 401:
                logging.warning("🔄 Token invalid, retrying with new token...")
                if self.get_access_token():
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    response = requests.post(self.api_url, headers=headers, json=payload, verify=False, timeout=30)
                    if response.status_code == 200:
                        result = response.json()
                        content = result['choices'][0]['message']['content']
                        return self._parse_response(content)
                return None
            else:
                logging.error(f"❌ GigaChat API error: {response.status_code}")
                logging.error(f"   Response: {response.text}")
                return None

        except Exception as e:
            logging.error(f"❌ GigaChat decomposition failed: {e}")
            return None

    def _parse_response(self, text: str) -> List[str]:
        steps = []
        
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Убираем нумерацию
            cleaned_line = line
            if '. ' in line:
                parts = line.split('. ', 1)
                if len(parts) > 1 and parts[0].isdigit():
                    cleaned_line = parts[1]
            elif ') ' in line:
                parts = line.split(') ', 1)
                if len(parts) > 1 and parts[0].isdigit():
                    cleaned_line = parts[1]
            elif line[0].isdigit() and ' ' in line:
                parts = line.split(' ', 1)
                if len(parts) > 1:
                    cleaned_line = parts[1]
            
            cleaned_line = cleaned_line.strip()
            if cleaned_line and len(cleaned_line) > 3:
                if cleaned_line.endswith('.'):
                    cleaned_line = cleaned_line[:-1]
                steps.append(cleaned_line)
        
        return steps if len(steps) >= 2 else None

# Глобальный экземпляр
gigachat_client = GigaChatClient()