FROM python:3.12-slim

# Корпоративный proxy в build (apt, pip). Передаётся из compose build.args / .env.
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    http_proxy=${HTTP_PROXY} \
    https_proxy=${HTTPS_PROXY} \
    no_proxy=${NO_PROXY}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY pvs_tracker ./pvs_tracker
COPY static ./static

RUN pip install --no-cache-dir . psycopg2-binary

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Linux container: default process on start (override via compose command: for workers).
# gunicorn не используем — один uvicorn на контейнер, масштабирование через app-1/app-2 + nginx.
CMD ["uvicorn", "pvs_tracker.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
