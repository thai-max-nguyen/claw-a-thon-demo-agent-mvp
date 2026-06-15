# claw-a-thon-demo-agent — Interview Q&A Agent

A minimal **Interview Q&A** Custom Agent for GreenNode AgentBase, built with
**FastAPI**. Send an interview question; get a concise, interview-style model
answer (STAR method for behavioral questions). The model is served by an
OpenAI-compatible endpoint (GreenNode MaaS), configured via environment variables.

## Endpoints

| Method | Path      | Body                | Response |
|--------|-----------|---------------------|----------|
| GET    | `/health` | —                   | `{"status": "ok"}` (200) |
| POST   | `/chat`   | `{"message": "..."}`| `{"status": "...", "answer": "...", "model": "..."}` |

If `LLM_API_KEY` is unset/empty the agent runs in **stub mode** and returns
`[stub — set LLM_API_KEY to enable live model] You asked: <message>` so the app
runs and tests pass without a key. The app uses the `openai` package if available,
otherwise raw `requests`, and degrades gracefully on any LLM/transport error.

## Environment variables

| Variable       | Description |
|----------------|-------------|
| `LLM_BASE_URL` | OpenAI-compatible base URL, e.g. `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` |
| `LLM_API_KEY`  | GreenNode MaaS API key. Empty → stub mode. |
| `LLM_MODEL`    | Model id, e.g. `Qwen2.5-7B-Instruct`. |

Copy `.env.example` to `.env` and fill in the values.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional — leave LLM_API_KEY empty for stub mode
uvicorn app:app --host 0.0.0.0 --port 8080
```

Health check:

```bash
curl http://127.0.0.1:8080/health        # -> {"status":"ok"}
```

Ask a question:

```bash
curl -X POST http://127.0.0.1:8080/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me about a time you handled conflict"}'
```

## Run with Docker

```bash
docker build -t claw-a-thon-demo-agent .
docker run -p 8080:8080 --env-file .env claw-a-thon-demo-agent
```

The container listens on port **8080** (required by AgentBase).

## Deploy to AgentBase

See **[DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md)** for the full deploy runbook
(portal login, registry, build/push, runtime create, health verification).

## Project structure

- `app.py` — FastAPI app (`/health` + `/chat`)
- `requirements.txt` — deps (fastapi, uvicorn, openai, requests, python-dotenv)
- `Dockerfile` — container image (python:3.11-slim, port 8080)
- `.env.example` — env var template
