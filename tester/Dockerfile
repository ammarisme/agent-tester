# Finite eval runner: `docker run agent-tester run --agent … --dataset …`
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY requirements.txt pyproject.toml README.md ./
RUN pip install -r requirements.txt
COPY agent_tester ./agent_tester
RUN pip install --no-deps . && useradd --create-home --uid 10001 runner

USER runner
WORKDIR /work
ENTRYPOINT ["agent-tester"]
CMD ["--help"]
