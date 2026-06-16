# AgentBase Custom Agent image — FastAPI growth agent (app.py), served on :8080.
FROM python:3.11-slim

WORKDIR /app

# deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app code only (tests, venv, .env excluded via .dockerignore)
COPY app.py telegram_bot.py ./

EXPOSE 8080

# Non-root for safety
RUN useradd -m -u 10001 appuser
USER appuser

# Container-level liveness (AgentBase also probes /health)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
