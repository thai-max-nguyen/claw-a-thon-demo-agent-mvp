# Build Plan — claw-a-thon-demo-agent (Interview Q&A Agent)

GreenNode Claw-a-thon Nhóm 2 (Summer Lubu). MVP: a deployable AgentBase **Custom Agent**.

## Use case

**Interview Q&A agent.** POST an interview question (optionally a target `role` and
candidate `context`); the agent returns a concise model answer (STAR method for
behavioral questions). LLM is the GreenNode MaaS endpoint (OpenAI-compatible),
configured via env vars `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`.

Request shape (POST `/invocations`):
```json
{"question": "Tell me about a time you handled conflict", "role": "Product Owner"}
```
Response: `{ "status": "success", "answer": "...", "model": "...", "session_id": "..." }`

## File layout (all flat in repo root — AgentBase Custom Agent structure)

| File | Purpose |
|------|---------|
| `main.py` | Entrypoint. `GreenNodeAgentBaseApp` with `@app.entrypoint` handler (Q&A logic, calls MaaS via `openai` client) and `@app.ping` health check. Binds `0.0.0.0:8080`. |
| `requirements.txt` | `greennode-agentbase`, `openai`, `python-dotenv`. |
| `Dockerfile` | `python:3.13-slim`, installs reqs, `EXPOSE 8080`, `CMD ["python","main.py"]`. |
| `.env.example` | Template for `LLM_*` + `GREENNODE_*`. Real `.env` is gitignored. |
| `.greennode.json` | SDK config (client_id/secret/identity) — empty template, gitignored. |
| `.gitignore` / `.dockerignore` | Exclude secrets (`.env`, `.greennode.json`, `*.credentials.json`) and venv. |
| `PLAN.md` / `README.md` | This plan + run/deploy instructions. |

Note: this is the **Custom** framework path (Basic template + `openai` SDK), not
LangChain/LangGraph — the use case is a single LLM call, no tools/graph needed.

## Local-test approach (automated now)

System Python is 3.9 (too old; SDK needs 3.10+). We use Homebrew **python3.13**:
```bash
/opt/homebrew/bin/python3.13 -m venv venv
./venv/bin/pip install -r requirements.txt
```
Two-tier test, no secrets required:
1. **Structure / import** — `python -c "import greennode_agentbase, openai, dotenv"`.
2. **Contract test** — start `python main.py`, then:
   - `GET /health` → expect **200** (required for AgentBase ACTIVE + public endpoint).
   - `POST /invocations` with a question → without `LLM_*` set returns
     `status:"degraded"` (graceful); with valid MaaS key returns `status:"success"`.

The agent degrades gracefully when `LLM_*` is unset, so health + structure pass
locally without a live MaaS key. The user fills `.env` from `.env.example` to get
real answers.

## Checklist: automated now vs. user runbook

**Done now (this build):**
- Step 3 — repo folder + agent scaffold created locally (not in Downloads).
- Step 4 — SIMPLE agent (Interview Q&A) built and **locally tested** (health 200 +
  invocations contract).
- AgentBase-ready: Dockerfile + requirements + flat structure + `.dockerignore`.

**Left to user runbook (blocked: Docker daemon down + portal needs OTP login):**
- **Step 1** — Log in GreenNode AI Portal (`aiplatform.console.vngcloud.vn`), get
  **MaaS API Key** + **IAM Client ID/Secret** (OTP to phone). User-only.
- **Step 2** — Create PUBLIC GitHub repo `claw-a-thon-demo-agent`, copy HTTPS link.
- **Step 5** — `git clone https://github.com/vngcloud/greennode-agentbase-skills`
  into the same folder so the deploy skills are available to the vibe tool.
- **Step 6** — Run skill: **"deploy my agent to AgentBase"** → provide Client
  ID/Secret + MaaS API Key + model (Gemma/Qwen/Minimax) + runtime size (2x4 or 4x4).
  Skill does Docker build + push (needs Docker Desktop running) → create runtime.
  Put real values in `.env` first: `LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`.
- **Step 7** — Verify ACTIVE on portal (AgentBase Runtime; PENDING→ACTIVE ~2-3 min).
- **Step 8** — Get endpoint, make public, confirm `<endpoint>/health` → 200, share URL.
- **Step 9** — `git push` agent to the PUBLIC GitHub repo.

**Why not automated:** Docker daemon is not running on this machine and the portal
requires phone-OTP login — both are user-only actions, so build/push/deploy/verify
are runbook steps, not scripted here.
