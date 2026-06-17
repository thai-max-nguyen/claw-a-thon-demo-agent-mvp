# GreenNode Claw-a-thon 2026 — Submission form fields

**Form:** https://greennode.ai/events/greennode-claw-a-thon (edit until 12:00 17/06)

| Field | Value |
|---|---|
| Team name | Summer Lubu |
| Track dự thi | **Data Analysis** |
| Agent name | Growth Assistant - Zalopay Mobility Services |
| Submitter | Nguyễn Lê Quang Thái |
| Email nhận kết quả | ThaiNLQ@vng.com.vn |

**Members:**
- Lâm Tiên Khải — KhaiLT@vng.com.vn
- Trần Thị Thu Nga — NgaTTT3@vng.com.vn
- Nguyễn Lê Quang Thái — ThaiNLQ@vng.com.vn

## 4 required artifacts
1. **Agent ACTIVE on AgentBase** — ✅ **ACTIVE**. Runtime `growth-assistant` (`runtime-8437757a`), model `google/gemma-4-31b-it`. Deployed via the official GreenNode AgentBase skill (IAM auth + `--from-cr`).
2. **Public GitHub repo + README** — ✅ public, polished README. Repo: https://github.com/thai-max-nguyen/claw-a-thon-demo-agent-mvp
3. **Demo video <3 min** — ✅ SharePoint (shared to @vng.com.vn): https://vngms-my.sharepoint.com/:f:/g/personal/khailt_vng_com_vn/IgCTlgAV8wZbRqKThgshpnFaAYrSFh-8P-mibf8jWZVlnBM?e=q9X2Ca
4. **Live endpoint (responds in incognito)** — ✅ `/health` → `{"status":"ok"}` 200: https://endpoint-4718fb93-6ff0-48fb-8723-f999e547970a.agentbase-runtime.aiplatform.vngcloud.vn — the bare URL redirects to a **live monitoring dashboard** at `/dashboard` (KPI tiles, progress charts, agent health, staged campaigns).

## CRM realization (demonstrated, draft-only)
4 DRAFT notifications created in the Zalopay CRM tool, mapped 1:1 to the agent's Action Plan (verified `INACTIVE`):
- 16550 — Reactivation · Grab (`app/2222`)
- 16559 — Acquisition · First Ride (`app/2222`)
- 16560 — Reactivation · XANH SM (`app/1653?id=6944`)
- 16561 — Reactivation · Be (`app/1341`)

Kept in sync: Confluence **Daily Output** (335581153) + **PRD** (335581080) carry a matching CRM-realization panel.

## Demo flow (Telegram, live)
`/run` → agent runs e2e (pull → forecast → anomalies → action plan), posts an executive report + proposed campaigns → human reviews, optionally **`/adjust`** the plan (e.g. `/adjust Grab 30K, drop Be`) → **`/confirm`** → bot **self-sources its own CRM session** (no manual token) and stages the **latest** version as DRAFT, replying with the exact content embedded in each (title, body, ZPA/ZPI deeplinks). Human publishes. Passive daily cron only suggests (Telegram + Confluence + dashboard) — it never writes to the CRM. Bot: `telegram_bot.py` + `crm_client.py` (HTML, chunked). Tests: 70.

## Thumbnail
16:9 — `Thumbnail AI Agent - Summer lubu.png`
