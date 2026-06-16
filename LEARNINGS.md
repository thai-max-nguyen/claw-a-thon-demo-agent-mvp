# Build Learnings — Growth Assistant (GreenNode Claw-a-thon 2026)

Hard-won, reusable lessons from building + deploying this agent. Read before the next AgentBase build.

## 🚀 GreenNode AgentBase deploy (the thing that took 8 failed tries)
- **Use the official skill** — `git clone github.com/vngcloud/greennode-agentbase-skills`, install into `.claude/skills/`. Don't hand-roll the deploy.
- **Auth = IAM service account (client-credentials)**, NOT the console cookie. Mint tokens at
  `POST https://iam.api.vngcloud.vn/accounts-api/v2/auth/token` (`-u CLIENT_ID:SECRET`, `grant_type=client_credentials`). These don't expire mid-flight — the console `vcloud-auth-access-token` does, which silently broke provisioning.
- **`--from-cr`** on `runtime.sh create` fetches CR creds inline + embeds correct `imageAuth`. Hand-built `imageAuth` was a key cause of `CREATING → ERROR` with **empty logs** (the pod never schedules / can't pull).
- **Image URL** = `{registryUrl}/{name}:{tag}` from `GET /cr/api/v1/repository` (here `vcr.vngcloud.vn/<repo>`). Build clean amd64: `docker buildx build --platform linux/amd64 --provenance=false --sbom=false --push`.
- **Models**: only BTC-enabled ones serve. `google/gemma-4-31b-it` worked + responsive; `qwen/qwen3-5-27b` + `minimax/minimax-m2.5` timed out. List via `aip.sh models list` (the model id for `LLM_MODEL` is the `path` field, e.g. `google/gemma-4-31b-it`).
- Result with the skill: **ACTIVE in ~30s** (vs 8 prior ERRORs).

## 📊 Atlas (Tableau) VizQL data — the partial-MTD trap
- The `YTM` worksheet per-merchant block is `[current-month MTD (PARTIAL), last full month, prior full, …]`.
  **Index 0 is partial** — never compute MoM as `(index0 − index1)`; it compares a half-month to a full month and falsely shows ~−25% on everything. Use **full months only** (index1+); the actionable signal is the **full-month forecast vs last full month**.
- Ratios (NPU/FPU, merchant share) are scale-invariant → safe to compute on partial MTD.

## 🔐 Browser session extraction (Arc / Chromium on macOS)
- Cookies in `~/Library/Application Support/Arc/User Data/Default/Cookies` (SQLite). Decrypt: key = `security find-generic-password -s "Arc Safe Storage" -w` → PBKDF2(key, salt=`saltysalt`, 1003, dklen=16, sha1) → AES-128-CBC, IV=16 spaces, strip `v10` prefix, then strip a 32-byte SHA256 domain prefix for recent Chromium.
- **HttpOnly cookies** aren't in `document.cookie` — read from the DevTools Application panel or the disk DB.
- The **disk snapshot lags** (Arc holds the live session in memory) → decrypted cookies can be stale. A replay needs the **full cookie set + browser headers** (Referer/Origin/UA/sec-fetch); OAuth/casdoor sessions (CRM) often can't be replayed by curl at all — use the SPA (its axios refreshes) or freshly-flushed cookies.

## 🔧 Tools / APIs
- **Confluence**: REST + Basic token at `~/.config/confluence-token`. Storage format = native `<table>`/`<ac:structured-macro>`; strip non-BMP emoji (400s).
- **Jira**: REST `/rest/api/2/issue/...` + cookie + `X-Atlassian-Token: no-check`. Attach files via multipart `POST .../attachments`.
- **GitHub README**: business-first beats tech-doc for mixed judges. Mermaid (flowchart/pie/sequence) renders natively. Capture/eyeball with headless Chrome (`--headless=new --screenshot --window-size=W,H --virtual-time-budget=20000`) then read the PNG.

## 🛡️ Principles that held up
- **No fabrication** — only claim what the dashboards prove; derived signals are fine *if computed from real pulls*. This honesty is a strength with judges.
- **No real business data in a public repo** — README figures + code targets are **illustrative**; real numbers stay internal / env-injected. Secrets gitignored, read in-memory only.
- **Draft-only CRM** — the agent proposes + embeds content; a human reviews & publishes.

## 📺 Live dashboard (cheap + on-brand)
- Serve monitoring as a `GET /dashboard` route on the **same deployed agent** (`app.py`) → instantly "live", no extra infra. Self-contained HTML (inline CSS + **SVG charts**, tiny JS polling `/health` + `/` for live status). Point the repo homepage at the `/dashboard` URL.
- **Owners want trends first** — lead with progress-over-time charts (MPU vs target line, CRM reactivation-lift bars). Fake/illustrative series is fine when there's no live feed; label it.
- **Zalopay brand**: royal blue `#0045FF` + green `#00D95F`, light bg, **Be Vietnam Pro**, rounded cards; green = healthy/up, amber/red = risk. Logo = blue "Zalo" + green "pay"; brand spelled **Zalopay**.
