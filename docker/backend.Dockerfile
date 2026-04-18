FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY src/Backend/API/requirements.txt /tmp/req-api.txt
COPY src/Backend/MQTTBroker/requirements.txt /tmp/req-mqtt.txt
COPY src/Backend/GTFS_RT/requirements.txt /tmp/req-gtfs.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install -r /tmp/req-api.txt \
    && python -m pip install -r /tmp/req-mqtt.txt \
    && python -m pip install -r /tmp/req-gtfs.txt

COPY src /app/src
COPY data /app/data

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /app/logs /app/received/images /app/received/data \
    && chown -R app:app /app

USER app

ENV PYTHONPATH=/app/src

