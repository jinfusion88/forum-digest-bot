FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]
ENV BOT_DB_PATH=/app/data/bot.db
ENV BOT_CONFIG_PATH=/app/data/config.yaml

CMD ["python", "bot.py"]
