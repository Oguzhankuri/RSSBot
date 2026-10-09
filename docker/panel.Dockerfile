# Panel + Telegram işçisi imajı. Kod imaja gömülmez: repo /app'e bağlanır,
# böylece "git pull" + yeniden başlatma yeterli; panelde düzenlenen formüller kaybolmaz.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

EXPOSE 8501
CMD ["streamlit", "run", "panel/app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true", "--browser.gatherUsageStats", "false"]
