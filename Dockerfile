FROM python:3.11-slim

WORKDIR /app

# Копируем все файлы проекта
COPY . .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем Node.js для веб-части
RUN apt-get update && apt-get install -y nodejs npm

# Устанавливаем зависимости для веб-приложения
WORKDIR /app/web/src
RUN npm install

# Возвращаемся в корень
WORKDIR /app

# Запускаем оба сервиса
CMD python main.py & cd web/src && npm run dev -- --host 0.0.0.0