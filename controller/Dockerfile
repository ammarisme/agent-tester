# Controller image: FastAPI API + Next.js UI + the shared runner package.
# Build context is the repository root:  docker build -f controller/Dockerfile .

# ── UI build ──────────────────────────────────────────────────────────
FROM node:20-bookworm-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY controller/frontend/package.json controller/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY controller/frontend/ ./
RUN npm run build

# ── Runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

# Only needed for RUNNER_MODE=docker (see docker-compose.docker-runner.yml).
ARG WITH_DOCKER_CLI=false

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=web /usr/local/bin/node /usr/local/bin/node

RUN if [ "$WITH_DOCKER_CLI" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
      && install -m 0755 -d /etc/apt/keyrings \
      && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
      && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
      && apt-get update \
      && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
      && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
COPY tester/requirements.txt /app/tester/requirements.txt
COPY controller/backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/tester/requirements.txt -r /app/backend/requirements.txt

COPY tester/pyproject.toml tester/README.md /app/tester/
COPY tester/agent_tester /app/tester/agent_tester
RUN pip install --no-deps /app/tester

COPY controller/backend/app /app/backend/app
COPY presets /app/presets
COPY datasets/samples /app/datasets/samples
COPY --from=web /web/.next/standalone /app/web
COPY --from=web /web/.next/static /app/web/.next/static
COPY controller/entrypoint.sh /app/entrypoint.sh

ENV PYTHONPATH=/app/backend \
    DATABASE_PATH=/data/agent_tester.db \
    JOBS_DIR=/data/jobs \
    PRESETS_DIR=/app/presets \
    SAMPLES_DIR=/app/datasets/samples \
    API_INTERNAL_URL=http://127.0.0.1:8000

RUN chmod +x /app/entrypoint.sh \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

USER app
VOLUME ["/data"]
EXPOSE 3000 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"

CMD ["/app/entrypoint.sh"]
