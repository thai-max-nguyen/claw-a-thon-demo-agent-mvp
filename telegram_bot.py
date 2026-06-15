"""Telegram bridge for the Interview Q&A Agent.

Long-polls Telegram getUpdates, routes slash commands to the agent's HTTP API,
and replies via sendMessage. Works in groups with privacy mode ON (it only
needs to see /commands, which Telegram always delivers).

Commands:
  /start, /help          -> usage
  /question [category]   -> generate an interview question (default behavioral)
  /ask <your question>   -> coaching model-answer (uses /chat)
  /evaluate <q> ||| <a>  -> score an answer (question and answer split by |||)

Env (from .env): TELEGRAM_BOT_TOKEN, AGENT_URL (default http://127.0.0.1:8080).
The token is read from the environment ONLY — never hardcode it here.
"""
import os
import time
import requests

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AGENT_URL = os.getenv("AGENT_URL", "http://127.0.0.1:8080").rstrip("/")
API = f"https://api.telegram.org/bot{TOKEN}"
CATS = ["behavioral", "technical", "system-design", "hr"]

HELP = (
    "🤖 *Interview Q&A Agent*\n"
    "/question [behavioral|technical|system-design|hr] — get a question\n"
    "/ask <your interview question> — get a coached model answer\n"
    "/evaluate <question> ||| <your answer> — score your answer 0–100\n"
    "/help — this message"
)


def agent_post(path: str, payload: dict) -> dict:
    r = requests.post(f"{AGENT_URL}{path}", json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def handle_text(text: str) -> str:
    """Pure router: command text -> reply text. Unit-testable, no network to TG."""
    text = (text or "").strip()
    # strip @botname suffix that groups append: /ask@mbs_analysis_bot
    if text.startswith("/"):
        head, _, rest = text.partition(" ")
        cmd = head.split("@", 1)[0].lower()
        arg = rest.strip()
    else:
        return ""  # privacy mode: ignore non-command chatter
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/question":
        cat = arg.lower() if arg.lower() in CATS else "behavioral"
        d = agent_post("/question", {"category": cat, "role": "Product Manager"})
        return f"❓ *{cat}* question:\n\n{d.get('question', '(none)')}"
    if cmd == "/ask":
        if not arg:
            return "Usage: /ask <your interview question>"
        d = agent_post("/chat", {"message": arg})
        return d.get("answer", "(no answer)")
    if cmd == "/evaluate":
        if "|||" not in arg:
            return "Usage: /evaluate <question> ||| <your answer>"
        q, a = [s.strip() for s in arg.split("|||", 1)]
        d = agent_post("/evaluate", {"question": q, "answer": a})
        return f"📊 Score: *{d.get('score')}/100*\n\n{d.get('feedback', '')}"
    return "Unknown command. Try /help"


def send(chat_id: int, text: str) -> None:
    requests.post(f"{API}/sendMessage",
                  json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=30)


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
                reply = handle_text(text)
                if reply and chat.get("id"):
                    send(chat["id"], reply)
        except Exception as e:
            print(f"loop error: {type(e).__name__}: {e}")
            time.sleep(3)


if __name__ == "__main__":
    main()
