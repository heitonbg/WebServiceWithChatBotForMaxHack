import json
import sys

import requests
import logging
import os
import uuid
from typing import List, Optional
from dotenv import load_dotenv

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))

load_dotenv()

class GigaChatClient:
    def __init__(self):
        self.auth_key = os.getenv('GIGACHAT_CLIENT_SECRET')
        self.access_token = None
        self.token_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        self.api_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

    def get_access_token(self) -> Optional[str]:
        try:
            if not self.auth_key:
                logging.warning(f"❌ GigaChat auth key not set: '{self.auth_key}'")
                return None

            logging.info(f"🔑 GigaChat auth key length: {len(self.auth_key) if self.auth_key else 0}")

            payload = {'scope': 'GIGACHAT_API_PERS'}
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json',
                'RqUID': str(uuid.uuid4()),  
                'Authorization': f'Basic {self.auth_key}'
            }

            response = requests.post(self.token_url, headers=headers, data=payload, verify=False, timeout=30)

            if response.status_code == 200:  
                result = response.json()
                self.access_token = result.get('access_token')
                logging.info("✅ GigaChat token obtained")
                return self.access_token
            else:
                logging.error(
                    f"❌ GigaChat token error: {response.status_code} - {response.text}")  
                return None

        except Exception as e:
            logging.error(f"❌ GigaChat token request failed: {e}")
            return None

    def decompose_task(self, task_title: str) -> Optional[List[str]]:
        """
        Разложить задачу на подзадачи с помощью GigaChat
        """
        try:
            if not self.access_token:
                token = self.get_access_token()
                if not token:
                    logging.warning("❌ No GigaChat token available")
                    return None

            prompt = f"""
    Разложи задачу "{task_title}" на 3-5 конкретных практических шагов для выполнения.

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

    Теперь разложи: "{task_title}"
    """

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

            response = requests.post(self.api_url, headers=headers, json=payload, verify=False, timeout=30)

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                steps = self._parse_response(content)

                if steps:
                    logging.info(f"✅ GigaChat decomposition successful for: {task_title}")
                    return steps
                else:
                    logging.warning(f"❌ Could not parse GigaChat response for: {task_title}")
                    return None
            else:
                logging.error(f"❌ GigaChat API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logging.error(f"❌ GigaChat decomposition failed: {e}")
            return None

    def _parse_response(self, text: str) -> List[str]:
        steps = []

        for line in text.strip().split('\n'):
            line = line.strip()

            if not line or not any(char.isdigit() for char in line):
                continue

            cleaned_line = line

            if '. ' in line:
                parts = line.split('. ', 1)
                if len(parts) > 1:
                    cleaned_line = parts[1].strip()
            elif ') ' in line:
                parts = line.split(') ', 1)
                if len(parts) > 1:
                    cleaned_line = parts[1].strip()
            elif ' - ' in line:
                parts = line.split(' - ', 1)
                if len(parts) > 1:
                    cleaned_line = parts[1].strip()
            else:
                parts = line.split(' ', 1)
                if len(parts) > 1 and parts[0].replace('.', '').replace(')', '').isdigit():
                    cleaned_line = parts[1].strip()

            if cleaned_line and len(cleaned_line) > 3:
                if cleaned_line.endswith('.'):
                    cleaned_line = cleaned_line[:-1]
                steps.append(cleaned_line)

        return steps if len(steps) >= 2 else None

    def get_daily_insights(self, daily_data):
        """Получить умные инсайты от GigaChat"""

        prompt = f"""
        Проанализируй продуктивность пользователя за сегодня и дай умные инсайты.

        ДАННЫЕ:
        - Выполнено задач: {len(daily_data['completed_tasks'])}
        - Невыполнено задач: {len(daily_data['pending_tasks'])}  
        - Процент выполнения: {daily_data['completion_rate']:.0%}
        - Эффективность по сложности: {daily_data['energy_efficiency']:.0%}
        - Уровень пользователя: {daily_data['user_level']}

        ВЫПОЛНЕННЫЕ ЗАДАЧИ: {', '.join(daily_data['completed_tasks'])}
        НЕВЫПОЛНЕННЫЕ ЗАДАЧИ: {', '.join(daily_data['pending_tasks'])}
        
        Говори в настоящем времени.

        ПРОАНИЛИЗИРУЙ:
        1. Общее настроение продуктивности (excellent/good/moderate/needs_improvement)
        2. 2-3 ключевых инсайта о паттернах работы
        3. 2-3 практических рекомендации
        4. Области для улучшения

        ФОРМАТ JSON:
        {{
            "mood": "excellent",
            "productivity_score": 85,
            "energy_efficiency": 75,
            "insights": ["инсайт 1", "инсайт 2"],
            "recommendations": ["рекомендация 1", "рекомендация 2"],
            "focus_areas": ["область 1", "область 2"]
        }}
        """

        try:
            response = self._make_gigachat_request(prompt)
            return json.loads(response)
        except:
            return None

    def _make_gigachat_request(self, prompt):
        """Универсальный метод для запросов к GigaChat"""
        try:
            if not self.access_token:
                token = self.get_access_token()
                if not token:
                    return None

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

            response = requests.post(self.api_url, headers=headers, json=payload, verify=False, timeout=30)

            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                logging.error(f"GigaChat API error: {response.status_code}")
                return None

        except Exception as e:
            logging.error(f"GigaChat request failed: {e}")
            return None

gigachat_client = GigaChatClient()