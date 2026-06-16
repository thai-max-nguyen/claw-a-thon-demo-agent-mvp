# Growth Assistant — Zalopay Mobility Services

**Team:** Summer Lubu · **Track:** Data Analysis · GreenNode Claw-a-thon 2026

An AI agent that does a Growth Marketer's daily dashboard analysis for **Zalopay Mobility (MBS)** — automatically.

## Problem
The Mobility Growth Marketer spends 2–3 hours every week manually tracking performance across **four disconnected Atlas dashboards** (MBS, Grab, Be, XANH SM), computing derived metrics, forecasting end-of-month numbers, and finding under-performing segments — before even getting to CRM push notifications.

## What it does (dashboard-only, no Excel)
1. **Pulls MTD** live from the Atlas (Tableau) dashboards — MBS KPI tiles + `Monthly` / `YTM` / `MTD` worksheets.
2. **Computes** derived metrics (FPU excl. NPU, RPU, retain rate) and a **full-month forecast** per segment (pacing = prev-month cumulative; confidence-gated).
3. **Compares** current MTD vs last month (same elapsed days) and **flags anomalies** with a 4-tier rule set; segments behind KPI are marked **At Risk**.
4. **Recommends actions** — per at-risk segment a 3W insight (What/Where/Why) + a prioritized campaign (P1 Acquisition + per-merchant P2 Reactivation).
5. **Generates CRM assets** — a ready-to-use segment (`Noti_[Type]_[Merchant]_DD/MM`, app-id include/exclude, estimated size) + A/B push-notification copy (real per-merchant deeplinks, send times, hypotheses) to paste into the Zalopay CRM tool.

## Output & delivery
- **Telegram group** — concise 5-section daily report.
- **Confluence** — clean daily log (collapsible per-day, tables, panels, TOC) + the team PRD.
- Sections: MTD Snapshot · Segment Health · Top Anomalies (3W) · Action Plan · CRM Ready + a one-line Bottom line.

## Value
Weekly analysis time cut from **2–3 hours to under 20 minutes** — the team focuses on decisions, not data wrangling.

## How it runs
- **Interactive (Telegram):** chat **`/run`** → the agent runs the full pipeline on demand (pull → forecast → anomalies → action plan) and posts the report; you review, then **`/confirm`** stages the proposed campaigns as **DRAFT** notifications in the CRM tool — you publish. Agent never publishes live.
- Scheduled daily **10:00** (`launchd`) with **Atlas auto-login** (self-heals the SSO session).
- An **audit gate** validates every number (segment sums, forecast bounds, cross-checks) and **aborts before sending** if anything fails — nothing fabricated.
- **CRM is draft-only** — the agent proposes; a human reviews + publishes (confirm-gated).

```bash
./run_mbs_growth.sh          # auto-login + pull + audit + post (Telegram + Confluence)
python3 mbs_growth.py --all  # same, without the SSO auto-login step
python3 -m pytest tests/     # 38 tests
```

## AgentBase endpoint (try the agent)
Deployed as a GreenNode AgentBase Custom Agent (`app.py`): `GET /health` → `{"status":"ok"}`; `POST /chat {"message":"…"}` answers questions about the MBS growth analysis using GreenNode MaaS.

## Layout
| File | Purpose |
|------|---------|
| `mbs_growth.py` | Pipeline: pull → forecast → anomaly → report → deliver |
| `crm_noti.py` | Action engine + CRM segment/noti generator (confirm-gated, draft-only) |
| `app.py` | FastAPI endpoint agent (AgentBase Custom Agent) |
| `run_mbs_growth.sh` | Daily wrapper (Atlas auto-login + run) |
| `tests/` | 38 tests |
| `DEMO_SCRIPT.md` · `SCOPE_crm_noti.md` · `DEPLOY_RUNBOOK.md` | Demo storyboard · CRM scope · deploy guide |

## CRM realization (demonstrated)
The Action Plan's 4 campaigns are pushed to the Zalopay CRM tool (Asset Management → Notification) as **DRAFT** notifications — real per-merchant deeplinks + A/B copy, ready for a human to review & publish. Draft-only by design; the agent never publishes.

| Noti | Action | Deeplink |
|------|--------|----------|
| Reactivation · Grab | re-engage May payers absent in June | `zalopay://launch/app/2222` |
| Acquisition · First Ride | net-new first-time riders (NPU constraint) | `zalopay://launch/app/2222` |
| Reactivation · XANH SM | re-engage lapsed XANH SM payers | `zalopay://launch/app/1653?id=6944` |
| Reactivation · Be | re-engage lapsed Be payers | `zalopay://launch/app/1341` |

## Notes
No secrets in the repo — credentials are env-injected / gitignored. Brand spelled **Zalopay**. Built on **GreenNode AgentBase** (Custom Agent runtime + MaaS LLM).
