FROM python:3.9-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && rm -rf /root/.cache/pip

COPY rss_main.py start.py dedup.py README.md ./

RUN mkdir -p /data

VOLUME ["/data"]

CMD ["python", "rss_main.py"]

LABEL maintainer="RSS Monitor Team" \
      description="RSS监控程序 - 支持多RSS源监控并通过Telegram发送通知" \
      version="2.0"
