FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN crawl4ai-setup

COPY app.py .

ENV PORT=11236
EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
