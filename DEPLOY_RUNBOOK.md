# Deploy Runbook — claw-a-thon-demo-agent

GreenNode Claw-a-thon Nhóm 2 ("Summer Lubu") — Build & Deploy Agent.

This is the **Interview Q&A agent** (FastAPI Custom Agent for GreenNode AgentBase,
resource type `/agent-runtimes`). Container contract is already satisfied:
- listens on **port 8080**
- `GET /health` returns `200`
- `POST /chat` `{"message": "..."}` returns an interview-style answer

**What is already done by the build agent (no action needed):**
- Step 2/3/4 — agent code built and **locally tested** (`app.py`, `app.py`, `Dockerfile`, `requirements.txt`, `TEST_REPORT.md`).
- Step 9 — repo is **PUBLIC and pushed**: https://github.com/thai-max-nguyen/claw-a-thon-demo-agent-mvp.git (branch `main`).

**What YOU must do (steps 1, 5, 6, 7, 8)** — they need OTP portal login + a running
Docker daemon, which cannot be automated headless. Follow A → G below, top to bottom.
Everything is copy-pasteable. Run all commands from the project root:

```bash
cd /Users/lap15964/clawathon-demo/claw-a-thon-demo-agent
```

---

## (A) Prereqs

| Check | How |
|-------|-----|
| Docker Desktop is **running** | `docker info` → must print server info, no error. Open Docker Desktop and wait for the whale icon to go steady if it errors. |
| `gh` is logged in (only needed if you re-push) | `gh auth status` → "Logged in to github.com". Repo is already pushed, so this is optional. |
| Python venv present (already tested) | `ls venv` exists. Optional local re-check: `source venv/bin/activate && uvicorn app:app --port 8080 &` then `curl -s localhost:8080/health` → `{"status":"ok"}`, then `kill %1`. |

---

## (B) Step 1 — Portal login → grab MaaS API Key + IAM Client ID/Secret

OTP-gated, user-only. Do this in a browser.

1. Open **https://aiplatform.console.vngcloud.vn** and log in (phone **OTP**).
2. **MaaS API Key**: AI Platform → MaaS → API Keys → create/copy key. This becomes `LLM_API_KEY`.
3. **IAM Client ID / Client Secret**: IAM console → Service Accounts → create (or open) a
   service account with the AgentBase full-access policy → copy **Client ID** and **Client Secret**.
   (The deployed container gets its own injected credentials; these are only for the deploy CLI.)
4. **(Optional) confirm model id**: in the deploy step you choose the served model
   (Gemma / Qwen / Minimax). You can also list them later with `/agentbase-llm`.

Keep these three values handy: **MaaS API Key**, **Client ID**, **Client Secret**.

### Configure `.env` (LLM only — never put IAM secrets here)

```bash
cp .env.example .env
```

Then edit `.env` and fill:
```
LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
LLM_API_KEY=<your MaaS API Key>
LLM_MODEL=<chosen model id, e.g. Qwen2.5-7B-Instruct>
```

> Do **NOT** set `GREENNODE_CLIENT_ID`, `GREENNODE_CLIENT_SECRET`,
> `GREENNODE_AGENT_IDENTITY`, or `GREENNODE_ENDPOINT_URL` in `.env` — AgentBase Runtime
> injects these automatically and manual values cause conflicts.

---

## (C) Install the AgentBase skills into `~/.claude/skills`

So Claude can run `/agentbase-deploy` from this project:

```bash
mkdir -p ~/.claude/skills
cp -R /Users/lap15964/clawathon-demo/summer-lubu-clawmander/greennode-agentbase-skills/.claude/skills/agentbase* ~/.claude/skills/
ls ~/.claude/skills
```

Expected: `agentbase`, `agentbase-deploy`, `agentbase-llm`, `agentbase-monitor`,
`agentbase-identity`, `agentbase-memory`, `agentbase-policy`, `agentbase-gateway`,
`agentbase-teardown`, `agentbase-wizard`.

---

## (D) Step 5+6 — Deploy via the skill (Docker build + push + create runtime)

Save your IAM credentials once (secret via stdin — never on the command line):

```bash
echo '<CLIENT_SECRET>' | bash ~/.claude/skills/agentbase/scripts/save_iam_credentials.sh \
  --client-id '<CLIENT_ID>' --secret-stdin
bash ~/.claude/skills/agentbase/scripts/check_credentials.sh iam   # expect: OK
```

Open Claude Code in this project and run the deploy skill:

```bash
cd /Users/lap15964/clawathon-demo/claw-a-thon-demo-agent
claude
```

Then in Claude type either:

```
/agentbase-deploy
```
or just:
```
deploy my agent to AgentBase
```

The skill presents a plan and asks for confirmation. Supply these answers when prompted:

| Prompt | Answer to give |
|--------|----------------|
| Resource type | **Custom Agent** (we have a Dockerfile) |
| Docker registry | **AgentBase managed Container Registry** (recommended; uses `--from-cr`) |
| Env file path | `.env` |
| Runtime name | `claw-a-thon-demo-agent` |
| Network mode | **PUBLIC** |
| Compute flavor | `2x4-general` (or `4x4-general`) — pick from the listed flavors |
| Build platform | **`linux/amd64`** (required — Apple Silicon must cross-build) |
| Model (MaaS) | choose Gemma / Qwen / Minimax via `/agentbase-llm`; matches your `.env` `LLM_MODEL` |
| Confirm to execute | `confirm` |

Under the hood the skill runs (you do NOT need to type these — listed for reference):
```bash
bash ~/.claude/skills/agentbase/scripts/cr.sh repo get
bash ~/.claude/skills/agentbase/scripts/cr.sh credentials docker-login
docker build --platform linux/amd64 -t <registryUrl>/<repo>/claw-a-thon-demo-agent:<tag> .
docker push <registryUrl>/<repo>/claw-a-thon-demo-agent:<tag>
bash ~/.claude/skills/agentbase/scripts/runtime.sh create \
  --name claw-a-thon-demo-agent \
  --image <registryUrl>/<repo>/claw-a-thon-demo-agent:<tag> \
  --flavor 2x4-general --env-file .env --from-cr \
  --network-mode PUBLIC --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50
```
Save the **RUNTIME_ID** from the create response — you need it below.

---

## (E) Step 7 — Verify ACTIVE on the portal runtime page

Portal: **https://aiplatform.console.vngcloud.vn/agent-runtime?tab=runtime** →
find `claw-a-thon-demo-agent` → **status = ACTIVE**. PENDING/CREATING is normal for ~2-3 min.

CLI equivalent:
```bash
bash ~/.claude/skills/agentbase/scripts/runtime.sh get <RUNTIME_ID>
```
Re-run until `"status": "ACTIVE"`.

---

## (F) Step 8 — Get endpoint, make public, check `/health` = 200

```bash
bash ~/.claude/skills/agentbase/scripts/runtime.sh endpoints list <RUNTIME_ID>
```
Find the **DEFAULT** endpoint and copy its `url` (this is the **public URL** — PUBLIC mode is internet-reachable).

Health check (must be `200`):
```bash
curl -s -o /dev/null -w "%{http_code}\n" "<endpoint-url>/health"
```

Smoke test the agent:
```bash
curl -s -X POST "<endpoint-url>/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"Tell me about a time you handled conflict"}'
```

Record the **public URL** for the demo (this is the deliverable for step 8).

---

## (G) Step 9 — Repo is already PUBLIC + pushed

Nothing to do. Confirm if needed:
```bash
gh repo view thai-max-nguyen/claw-a-thon-demo-agent-mvp --json visibility,url
```
Expected: `"visibility": "PUBLIC"`. If you make further code changes, re-deploy via (D)
(the skill runs `runtime.sh update <RUNTIME_ID> ... --from-cr`) and push with
`git push origin main`.

---

## Common errors → fixes

| Error / symptom | Cause | Fix |
|-----------------|-------|-----|
| `Cannot connect to the Docker daemon` | Docker Desktop not running | Start Docker Desktop, wait for steady whale, re-run `docker info`. |
| `check_credentials.sh iam` → MISSING | IAM creds not saved | Re-run the `save_iam_credentials.sh … --secret-stdin` command in (D). |
| `401 Unauthorized` on API calls | Expired/invalid IAM token | `TOKEN=$(bash ~/.claude/skills/agentbase/scripts/get_token.sh --force)`; verify Client ID/Secret. |
| `403 Forbidden` | Service account lacks AgentBase policy | Grant AgentBase full-access policy at https://iam.console.vngcloud.vn, retry. |
| `docker push` → `unauthorized` / `denied` | Not logged in to the CR, or stale secret | `bash ~/.claude/skills/agentbase/scripts/cr.sh credentials docker-login` (re-run). |
| `docker push` → `denied` after retag | Wrong repo segment in tag | Re-tag as `{registryUrl}/{repoName}/<image>:<tag>` — read both from `cr.sh repo get`. |
| Build fails on Apple Silicon / runtime won't start | Image is arm64, runtime needs amd64 | Rebuild with `--platform linux/amd64`. |
| Status stuck `CREATING` / `ERROR` | Container crash, wrong port, or `/health` failing | Must listen on **8080** + `GET /health`→200 (already true here); check logs via `/agentbase-monitor`. |
| Endpoint returns `502` | Container not ready yet | Wait for ACTIVE, retry the health check a few times. |
| `/health` not 200 after ACTIVE | Image-pull auth stale | `runtime.sh update <RUNTIME_ID> … --from-cr` to re-embed CR credentials. |
| Runtime fails to pull image after credential reset | Stale `imageAuth` | `runtime.sh update <RUNTIME_ID> … --from-cr`. |
| Push fails: quota exceeded | CR repo near quota | Prune: `cr.sh artifacts delete --image <name> --digest <digest>`. |
| `OTP not received` at portal login | Phone/SIM delay | Wait 60s and request a new code; confirm the phone bound to the VNG Cloud account. |
