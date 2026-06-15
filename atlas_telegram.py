"""Atlas -> Telegram: read the Atlas (Tableau) dashboard live and post a summary.

Replaces the "wait for the Excel file" step — the agent reads Atlas directly via
the existing bat_signal Atlas bootstrap (Chrome SSO cookies + VizQL), formats a
headline, and sends it to Telegram.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (the group/DM chat id — get it by
sending /start@mbs_analysis_bot in the group, then GET getUpdates).
Atlas session must be alive (atlas_auto_login.py keeps it fresh).
"""
import os
import sys
import json
import urllib.request

sys.path.insert(0, os.path.expanduser("~/.config/life-ops"))


def read_atlas() -> dict:
    import bat_signal as bs
    chrome = bs.extract_chrome_cookies(["atlas.vng.com.vn"])
    cookies = chrome["atlas.vng.com.vn"]
    if "workgroup_session_id" not in cookies:
        raise SystemExit("Atlas session dead — run atlas_auto_login.py first")
    data = bs.pull_atlas_parallel(cookies)
    ekyc = data[bs.EKYC_VIEW]
    dates = ekyc.get("str_vals", [])[:29]
    reals = ekyc.get("real_vals", [])
    return {"dates": dates, "reals": reals, "n_dates": len(dates), "n_reals": len(reals)}


def format_msg(a: dict) -> str:
    latest = a["dates"][-1] if a["dates"] else "?"
    sample = ", ".join(f"{v:.3f}" for v in a["reals"][:5]) if a["reals"] else "—"
    return (f"📈 Atlas eKYC dashboard — live read\n"
            f"Latest date in view: {latest}\n"
            f"Series points: {a['n_reals']} values across {a['n_dates']} dates\n"
            f"Head sample: {sample}\n"
            f"(Full SR/flow breakdown available — reply /action for a drill-down.)")


def send_telegram(text: str) -> str:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not tok:
        return "FAIL: TELEGRAM_BOT_TOKEN not set"
    if not chat:
        return ("FAIL: no TELEGRAM_CHAT_ID — send '/start@mbs_analysis_bot' in the "
                "Clawathon group, then GET /getUpdates to read chat.id, set TELEGRAM_CHAT_ID")
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                 data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20)
        return "SENT"
    except Exception as e:
        return f"FAIL: {type(e).__name__}: {e}"


def main():
    a = read_atlas()
    msg = format_msg(a)
    print(msg)
    print("\n[telegram]", send_telegram(msg))


if __name__ == "__main__":
    main()
