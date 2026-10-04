FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && useradd --create-home --uid 10001 mock
COPY echo_agent.py .
USER mock
EXPOSE 9999
CMD ["uvicorn", "echo_agent:app", "--host", "0.0.0.0", "--port", "9999", "--no-access-log"]
