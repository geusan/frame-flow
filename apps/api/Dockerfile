FROM node:22-bookworm-slim AS agent-clis

ARG CODEX_CLI_VERSION=0.151.0
ARG CLAUDE_CODE_VERSION=2.1.251
RUN npm install -g "@openai/codex@${CODEX_CLI_VERSION}" "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk libegl1 libgl1 libgles2 && rm -rf /var/lib/apt/lists/*
COPY apps/api/requirements.txt apps/api/requirements-docker.txt ./
RUN pip install --no-cache-dir torch==2.13.0+cpu --index-url https://download.pytorch.org/whl/cpu
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libopus-dev \
    && pip install --no-cache-dir -r requirements-docker.txt \
    && apt-get purge -y --auto-remove build-essential pkg-config libopus-dev \
    && rm -rf /var/lib/apt/lists/* /root/.cache/puccinialin
COPY --from=agent-clis /usr/local/bin/node /usr/local/bin/node
COPY --from=agent-clis /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex \
    && ln -s ../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe /usr/local/bin/claude
COPY apps/api/app ./app
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/migrations ./migrations
COPY packages/schemas ./packages/schemas
COPY .codex/skills ./.codex/skills
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
