FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 1000 frameflow \
    && useradd --uid 1000 --gid frameflow --create-home frameflow \
    && apt-get update \
    && apt-get install -y --no-install-recommends blender ffmpeg fonts-noto-cjk libegl1 libgl1 libgles2 python3-numpy \
    && rm -rf /var/lib/apt/lists/*

COPY --chown=frameflow:frameflow apps/api/app/blender/scripts /app/scripts
COPY --chown=frameflow:frameflow apps/blender-worker/service.py /app/service.py

USER frameflow
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3)"]
CMD ["python", "/app/service.py"]
