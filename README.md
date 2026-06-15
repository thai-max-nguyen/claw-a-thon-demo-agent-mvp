# Interview Q&A Agent — GreenNode AgentBase (Claw-a-thon Nhóm 2)

A Custom Agent for **GreenNode AgentBase**: generates interview questions, gives
STAR-method coaching answers, and scores candidate answers — backed by an
OpenAI-compatible LLM (GreenNode MaaS).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness probe → `{"status":"ok"}` (200) |
| GET | `/` | Agent metadata + capabilities |
| POST | `/question` | Generate an interview question (`category`, `role`) |
| POST | `/chat` | Coaching model-answer to an interview question |
| POST | `/evaluate` | Score a candidate answer 0–100 + feedback |
| GET | `/session/{sid}` | Retrieve a session's Q&A history |
| DELETE | `/session/{sid}` | Clear a session |

Categories: `behavioral`, `technical`, `system-design`, `hr`.

## Run locally

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# stub mode (no key) — service boots, /health 200, /chat returns a stub
uvicorn app:app --host 0.0.0.0 --port 8080
```

### Live model (GreenNode MaaS)

Set the three env vars (see `.env.example`), then run as above:

```bash
export LLM_BASE_URL="https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1"
export LLM_API_KEY="<your MaaS API key>"
export LLM_MODEL="google/gemma-4-31b-it"   # or another enabled model
```

## Test

```bash
bash tests/smoke.sh          # boots the app + checks every endpoint
```

## Deploy

See **[DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md)** — the GreenNode AgentBase deploy
steps (portal login, `/agentbase-deploy`, verify ACTIVE, public endpoint).

## Example (live)

```
POST /chat  {"message":"Tell me about a time you handled a tight deadline."}
→ 200  {"status":"success","answer":"…STAR-method model answer…","model":"google/gemma-4-31b-it"}
```
