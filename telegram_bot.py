"""Telegram bridge for the Growth Assistant.

Long-polls Telegram getUpdates, routes slash commands, replies via sendMessage.
Works in groups with privacy mode ON (it only sees /commands).

Commands:
  /run      -> full daily analysis (pull → forecast → anomalies → action plan + CRM drafts)
  /confirm  -> stage the proposed noti as DRAFT in the CRM tool (you review, then publish)
  /help     -> usage

Env (from .env): TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_ID. Token read from env ONLY.
"""
import os
import time
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"

HELP = (
    "🤖 <b>MBS Growth Assistant</b>\n"
    "/run — full daily analysis (pull → forecast → anomalies → action plan + CRM noti drafts)\n"
    "/confirm — stage the proposed noti as DRAFT in the CRM tool for your review\n"
    "/help — this message"
)

# in-memory hand-off between /run and /confirm (single-process long-poll bot)
PENDING = {}

# the 4 DRAFT notis already staged in CRM, keyed by action identity
CRM_LINK = "https://office.zalopay.vn/ge/crm/tool/asset-management/notifications"
NOTI_IDS = {"Grab": 16550, "_ACQ": 16559, "XANH SM": 16560, "Be": 16561}


def run_e2e() -> dict:
    """Live end-to-end: Atlas pull -> forecast -> audit -> action plan + noti drafts.
    Returns {report, actions, ok}. Posts to Confluence best-effort. No fabrication —
    every number comes from the live dashboards; aborts the send if the audit fails."""
    import mbs_growth as g, crm_noti
    cookies = g.bs.extract_chrome_cookies(["atlas.vng.com.vn"])["atlas.vng.com.vn"]
    if "workgroup_session_id" not in cookies:
        return {"error": "Atlas session expired — run ./run_mbs_growth.sh to re-login, then /run again."}
    biz = g.pull_mbs_business(cookies)
    seg = g.pull_segments(cookies, biz["MPU"]["value"], biz["NPU"]["value"])
    merch = g.pull_merchant_mpu(cookies)
    series = g.pull_merchant_series(cookies)
    vol = g.pull_merchant_volume(cookies)
    fc = g.forecast(biz, cookies)
    fc["_target"] = g.MPU_TARGET.get(g._month_key())
    fc_reach = (fc.get("MPU_fc") / fc["_target"]) if (fc.get("MPU_fc") and fc.get("_target")) else None
    ok, _ = g.audit(biz, seg, merch)
    signals = g.derive_signals(biz, merch, series, vol, fc)
    actions = crm_noti.build_actions(biz, seg, merch, fc, signals)
    report = g.build_report(biz, seg, merch, fc, actions)
    if ok:  # mirror to Confluence Daily Output (best-effort; never blocks the chat reply)
        try:
            day = g.build_confluence_day(biz, seg, merch, fc, actions)
            g.paste_confluence(report, biz["MPU"]["value"], fc_reach, actions,
                               page_id="335581153", new_title="MBS Growth Assistant — Daily Output", day_storage=day)
        except Exception:
            pass
    return {"report": report, "actions": actions, "ok": ok}


def handle_text(text: str) -> str:
    """Pure router: command text -> reply text. Unit-testable, no network to TG."""
    text = (text or "").strip()
    # strip @botname suffix that groups append: /run@mbs_analysis_bot
    if text.startswith("/"):
        head, _, rest = text.partition(" ")
        cmd = head.split("@", 1)[0].lower()
        arg = rest.strip()
    else:
        return ""  # privacy mode: ignore non-command chatter
    if cmd in ("/start", "/help"):
        return HELP
    if cmd in ("/run", "/growth"):
        res = run_e2e()
        if res.get("error"):
            return "⚠️ " + res["error"]
        PENDING["actions"] = res["actions"]
        n = len(res["actions"])
        tail = (f"\n\n— — —\n✅ Audit passed. <b>{n} CRM noti drafts</b> ready (per-merchant deeplinks + A/B copy).\n"
                f"Reply <b>/confirm</b> to stage them as <b>DRAFT</b> in the CRM tool — you review &amp; publish; I never publish live."
                if res["ok"] else "\n\n⚠️ Audit failed — not sending. Numbers need a re-pull.")
        return res["report"] + tail
    if cmd == "/confirm":
        actions = PENDING.get("actions")
        if not actions:
            return "Nothing to confirm yet. Run <b>/run</b> first, review the plan, then <b>/confirm</b>."
        import crm_client
        try:
            staged = crm_client.stage_drafts(actions)   # full-auto: self-sources its own CRM session
        except crm_client.CrmSessionError as e:
            return f"⚠️ {e}"
        except Exception as e:
            return f"⚠️ CRM push failed: {type(e).__name__}: {str(e)[:90]}"
        blocks = ["✅ <b>Confirmed.</b> Staged as <b>DRAFT</b> (INACTIVE) in the Zalopay CRM tool — "
                  "here is exactly what I embedded in each noti:"]
        for s in staged:
            blocks.append(
                f"\n<b>#{s['id']}</b> · <code>{s['name']}</code>\n"
                f"   • <b>Title</b> — {s['title']}\n"
                f"   • <b>Body</b> — {s['body']}\n"
                f"   • <b>ZPA</b> — <code>{s['zpa']}</code>\n"
                f"   • <b>ZPI</b> — <code>{s['zpi']}</code>")
        blocks.append(f"\n👉 Review &amp; publish: {CRM_LINK}\n"
                      "<i>Draft-only — the agent proposes &amp; embeds the content; you review and activate.</i>")
        return "\n".join(blocks)
    return "Unknown command. Try /help"


def send(chat_id: int, text: str) -> None:
    # The agent's reports are HTML (<b>/<pre> tables) and can exceed Telegram's 4096-char
    # limit — reuse the pipeline's HTML normaliser + chunker so long reports render + fit.
    import mbs_growth as g
    for chunk in g._chunk(g._tg_html(text)):
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)


def main() -> None:
    if not TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set (see .env)")
    offset = None
    print(f"bridge up — agent={AGENT_URL}")
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{API}/getUpdates", params=params, timeout=40).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or u.get("channel_post") or {}
                chat = msg.get("chat", {})
                text = msg.get("text", "")
                # /run is a live multi-step pull (~30s) — ack first so the chat isn't silent
                low = (text or "").strip().split("@", 1)[0].lower()
                if chat.get("id") and (low.startswith("/run") or low.startswith("/growth")):
                    send(chat["id"], "⏳ Running end-to-end: Atlas pull → forecast → anomalies → action plan…")
                reply = handle_text(text)
                if reply and chat.get("id"):
                    send(chat["id"], reply)
        except Exception as e:
            print(f"loop error: {type(e).__name__}: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
