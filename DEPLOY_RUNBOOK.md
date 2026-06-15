# Deploy Runbook — claw-a-thon-demo-agent (GreenNode AgentBase Custom Agent)

This agent ships as a Docker image and runs on AgentBase Runtime (Custom Agent,
resource type `/agent-runtimes`). Container contract: listens on **port 8080**,
`GET /health` returns 200. Both are already satisfied by `app.py` + `Dockerfile`.

Use the `/agentbase-deploy` skill to drive the deploy. The steps below summarize
what it will ask for.

## Prerequisites (user-only, OTP login)

1. **GreenNode AI Portal** (`https://aiplatform.console.vngcloud.vn`) — log in (phone OTP).
2. **MaaS API Key** — from the portal (or via `/agentbase-llm`). Goes into `.env` as `LLM_API_KEY`.
3. **IAM Client ID / Secret** — service account for calling platform APIs during deploy.
4. **Docker Desktop running** — needed for the build/push step.

## Configure env

```bash
cp .env.example .env
# Fill in:
#   LLM_BASE_URL=https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
#   LLM_API_KEY=<your MaaS API key>
#   LLM_MODEL=<chosen model id, e.g. Qwen2.5-7B-Instruct>
```

Do **not** set `GREENNODE_CLIENT_ID` / `GREENNODE_CLIENT_SECRET` /
`GREENNODE_AGENT_IDENTITY` / `GREENNODE_ENDPOINT_URL` in `.env` — AgentBase Runtime
injects these automatically.

## Deploy steps (via `/agentbase-deploy`)

1. **Registry** — recommended: AgentBase managed Container Registry (`cr.sh repo get`,
   then `cr.sh credentials docker-login`). External registries also supported.
2. **Build** — `docker build --platform linux/amd64 -t <registry>/claw-a-thon-demo-agent:<tag> .`
   (amd64 is required when building on Apple Silicon).
3. **Push** — `docker push <registry>/claw-a-thon-demo-agent:<tag>`.
4. **Create runtime** — `runtime.sh create --name claw-a-thon-demo-agent
   --image <registry>/claw-a-thon-demo-agent:<tag> --flavor <flavor> --env-file .env
   --from-cr --network-mode PUBLIC`. Pick a flavor from `runtime.sh flavors`
   (e.g. `2x4-general` or `4x4-general`).
5. **Wait for ACTIVE** — `runtime.sh get <RUNTIME_ID>` (PENDING → ACTIVE, ~2-3 min).
6. **Endpoint + health** — `runtime.sh endpoints list <RUNTIME_ID>`, then
   `curl -s -o /dev/null -w "%{http_code}" <endpoint-url>/health` → expect `200`.
7. **Smoke test** — `curl -X POST <endpoint-url>/chat -H "Content-Type: application/json"
   -d '{"message":"Tell me about a time you handled conflict"}'`.

## Why parts are manual

Docker daemon and the OTP portal login are user-only actions, so build/push/deploy/
verify are runbook steps rather than scripted here.
