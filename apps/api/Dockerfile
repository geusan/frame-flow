FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.txt apps/api/requirements-docker.txt ./
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libopus-dev \
    && pip install --no-cache-dir -r requirements-docker.txt \
    && apt-get purge -y --auto-remove build-essential pkg-config libopus-dev \
    && rm -rf /var/lib/apt/lists/* /root/.cache/puccinialin
COPY apps/api/app ./app
COPY .codex/skills ./.codex/skills
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
