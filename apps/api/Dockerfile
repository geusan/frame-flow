FROM node:22-bookworm-slim AS agent-clis

ARG CODEX_CLI_VERSION=0.151.0
ARG CLAUDE_CODE_VERSION=2.1.251
RUN npm install -g "@openai/codex@${CODEX_CLI_VERSION}" "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

FROM python:3.11-slim

ARG PIP_VERSION=26.2.1
ARG SETUPTOOLS_VERSION=84.0.0
ARG WHEEL_VERSION=0.48.0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --gid 1000 frameflow \
    && useradd --uid 1000 --gid frameflow --create-home frameflow \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk libegl1 libgl1 libgles2 \
    && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.lock.txt apps/api/requirements-docker.txt ./
RUN pip install --no-cache-dir \
    "pip==${PIP_VERSION}" \
    "setuptools==${SETUPTOOLS_VERSION}" \
    "wheel==${WHEEL_VERSION}"
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libopus-dev \
    && pip install --no-cache-dir --require-hashes -r requirements.lock.txt \
    && pip install --no-cache-dir -r requirements-docker.txt \
    && apt-get purge -y --auto-remove build-essential pkg-config libopus-dev \
    && rm -rf /var/lib/apt/lists/* /root/.cache/puccinialin
RUN rm -rf /usr/local/lib/python3.11/site-packages/pip \
    /usr/local/lib/python3.11/site-packages/pip-*.dist-info \
    /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.11
COPY --from=agent-clis /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-clis /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN rm -rf /usr/local/lib/node_modules/corepack /usr/local/lib/node_modules/npm \
    && ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude
COPY --chown=frameflow:frameflow apps/api/app ./app
COPY --chown=frameflow:frameflow apps/api/alembic.ini ./alembic.ini
COPY --chown=frameflow:frameflow apps/api/migrations ./migrations
COPY --chown=frameflow:frameflow packages/schemas ./packages/schemas
COPY --chown=frameflow:frameflow .codex/skills ./.codex/skills
RUN mkdir -p /home/frameflow/.cache/mediapipe /home/frameflow/.codex \
    && chown -R frameflow:frameflow /home/frameflow
USER frameflow
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
