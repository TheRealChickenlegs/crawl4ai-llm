FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN crawl4ai-setup

COPY app.py .

EXPOSE ${PORT}

CMD uvicorn app:app --host 0.0.0.0 --port ${PORT}