# Scope — CRM Notification Auto-Setup (confirm-gated)

## Goal
Extend the daily Growth Assistant: after it posts the analysis to Telegram, let it
**auto-create the CRM segment + notification** for a recommended re-engagement campaign —
but **only after explicit human confirmation**, with a feedback loop to adjust strategy first.

## SOP (target flow)
1. **Analyze (existing):** daily dashboard pull → report to Telegram + Confluence (live now).
2. **Recommend:** when an anomaly fires (per her 4-tier rules), the agent appends an
   *Action Recommendation* card (her Step-4 format): Problem · Possible Cause · Suggested Action
   (Target segment · Campaign · Channel · Success metrics).
3. **Confirm gate (hard):** agent posts the proposed CRM setup to Telegram and **waits**.
   - Reply `confirm` / `ok setup` → agent proceeds.
   - Any other reply = **feedback** → agent revises the segment/campaign and re-proposes.
   - No reply → nothing happens. **Never auto-sets up without an explicit confirm.**
4. **Setup (on confirm only):** agent creates the segment + the notification in the CRM tool,
   then posts back the created segment name + noti id for the record.

## CRM actions to automate (from her doc)
CRM tool: `https://office.zalopay.vn/ge/crm/tool/user-profile/segments`
- **Create segment:** Segments → Add new → name = `Noti + <segment> + DD/MM` → conditions
  (e.g. *paid MBS in May, not returned in June, as of segment date*) → Save.
  App IDs: **Grab 222 · Be 1063 · Xanhsm 3095**.
- **Create noti:** CRM tool → noti → Add new → bind to the segment → channel (Push / Zalo OA) → schedule.

## Trigger logic (grounded in real data, no fabrication)
- Source = the same dashboard metrics the daily report already pulls (segments + merchant MPU + deltas).
- A recommendation is emitted only when a metric crosses her thresholds (e.g. RSPU/RPU drop ≤ −1%,
  or a merchant's NPU/retention drop). The segment definition is **derived from the metric that fired**
  (e.g. "inactive 30–60d" for an RSPU drop), never invented.
- Each proposal states exactly which metric + value triggered it.

## Guardrails
- **Confirm-only.** No CRM write without an explicit Telegram confirm from the user.
- **Dry-run preview.** The proposal shows the exact segment name, conditions, app-ids, channel before any write.
- **Idempotent / no dup.** Check for an existing segment with the same name+date before creating.
- **Audit log.** Every CRM write logged (who confirmed, when, segment id, noti id).
- **Reversible.** Capture the created segment/noti ids so a setup can be undone.
- **No PII in Telegram.** Only segment definitions + counts, never user lists.

## Access investigation (2026-06-16) — findings
- The CRM tool is an **OAuth2-protected SPA**: UI `…/ge/crm/tool/user-profile/segments` →
  redirect `/login/oauth/authorize?client_id=78478009fe3f12bde945&scope=read profile email`,
  gateway `/ge`, callback `/ge/callback`.
- **A backend JSON API exists** (API automation viable, no Playwright needed):
  `GET https://office.zalopay.vn/api/crm/tool/user-profile/segments` → JSON
  `{"status":"error","msg":"Unauthorized operation"}` without auth. The `/api/crm/tool/...`
  base mirrors the UI path, so create-segment + create-noti almost certainly POST to siblings.
- **No live session right now** (0 office.zalopay.vn cookies — not logged in).
- ⚠️ **Scope risk:** the OAuth scope is `read profile email` — may be **read-only**. Need to verify
  the API permits POST (create segment/noti) with the user's token, or whether a write scope/role is required.

### Next step to finish the API spec (needs user)
1. Log into the CRM tool in Chrome once (complete VNG SSO).
2. Then: extract the office.zalopay.vn session cookie → `GET /api/crm/tool/user-profile/segments`
   (confirm read works) → capture the SPA's create-segment + create-noti XHR (endpoint + payload schema).
3. Confirm whether POST/create is allowed with that token (scope check).

## Open questions (remaining)
1. **Write permission/scope** — does the user's OAuth token allow POST create, or read-only?
2. **Auth.** Same VNG SSO as Atlas? Can we reuse the cookie-extraction path, or is a service account needed?
3. **Segment condition schema.** Exact field/operator names the CRM expects for "paid MBS month X, not in month Y".
4. **Approval authority.** Who can confirm (just you, or a named approver list)?
5. **Channels + caps.** Allowed channels (Push / Zalo OA), frequency caps, quiet hours, opt-out handling.

## Phasing
- **P0 (now):** this scope + add the Action-Recommendation card to the daily report (read-only, no CRM write).
- **P1:** confirm-gate plumbing on Telegram (`confirm` / feedback parser) + dry-run proposal message.
- **P2:** CRM segment create (API or UI automation) behind the confirm gate, with audit log + undo.
- **P3:** CRM noti create + post-back of ids; idempotency + guardrails hardened.

## Non-goals (for now)
- No autonomous sending without confirm. No mass targeting. No PII export to Telegram.
