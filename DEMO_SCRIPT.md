# Demo video script — Growth Assistant · Zalopay Mobility Services
**Team:** Summer Lubu · **Track:** Data Analysis · target length **~2–3 min** · screen-record.

> Goal of the video: show the agent turning 4 raw dashboards into a daily decision + ready-to-use CRM actions — the "2–3h → <20 min" story.

---

### 0:00–0:20 · Hook (the problem)
- Voiceover: "Mỗi tuần, Growth Marketer của Zalopay Mobility mất 2–3 tiếng ghép số tay từ 4 dashboard rời rạc — MBS, Grab, Be, XANH SM."
- Screen: flash the 4 Atlas dashboards (MBS + 3 merchants).

### 0:20–0:45 · The agent runs (one command)
- Terminal: `./run_mbs_growth.sh`
- Narrate the stages as they print: Atlas auto-login → pull tiles → segments + merchant MPU → forecast → **AUDIT PASSED** → report → 4 actions → Confluence + Telegram.
- Point: "Một lệnh, không chờ Excel — đọc thẳng dashboard."

### 0:45–1:25 · The daily output (Telegram + Confluence)
- Telegram group: scroll the 5-section message — MTD Snapshot, Segment Health (🟡 at risk), Top Anomalies (3W), Action Plan, CRM Ready, Bottom line.
- Call out 2 real numbers: **MPU 548,636 → forecast 95.1% of target**; **NPU flat → acquisition is the constraint**.
- Confluence daily log: show the collapsible per-day entry (tables + panels), TOC, latest-status panel.

### 1:25–2:05 · From insight to action (the differentiator)
- Show the 4 prioritized actions: P1 Acquisition + per-merchant P2 Reactivation (Grab/XANH/Be).
- Open one action panel: 3W cause → CRM segment (`Noti_RPU_Grab_Churn_…`, app-id include/exclude, ~129K size) → A/B noti copy with real deeplinks + send times.
- Then the CRM tool: show segment **16550 (Draft)** + the noti fields ready to paste.
- Point: "Tới tận CRM segment + nội dung noti A/B — chỉ việc review & publish."

### 2:05–2:30 · Trust + close
- One line on guardrails: "Mọi số đều truy ra dashboard thật, có audit-gate, không bịa; CRM luôn để **draft**, người duyệt."
- Show: launchd 10:00 daily + 38 tests passing.
- Close: "Growth Assistant — từ 2–3 tiếng còn dưới 20 phút. Team Summer Lubu."

---

### Capture checklist
- [ ] 4 dashboards open (logged in) for the hook
- [ ] Terminal at project root, font size up
- [ ] Telegram group + Confluence daily-output page (MVP Output MBS) open
- [ ] CRM tool on segment 16550 (Draft) + its noti editor
- [ ] Record 1440p, trim to ~2:30, export `Demo - Growth Assistant - Summer Lubu.mp4`
- [ ] Thumbnail: `Thumbnail AI Agent - Summer lubu.png` (already referenced in the submit doc)
