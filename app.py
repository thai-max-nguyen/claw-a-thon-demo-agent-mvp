"""Interview Q&A Custom Agent — FastAPI app for GreenNode AgentBase.

Endpoints:
  GET  /health  -> {"status": "ok"}  (200)  — AgentBase health probe
  POST /chat    -> {"message": "..."} -> interview-style Q&A answer

The LLM is an OpenAI-compatible endpoint (GreenNode MaaS), configured via:
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

If LLM_API_KEY is unset/empty the app returns a clear stub answer so it runs
(and tests pass) WITHOUT a key. Uses the `openai` package if available, else
falls back to raw `requests`; degrades gracefully if neither is present.
"""

import os

from fastapi import FastAPI
from pydantic import BaseModel

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass

app = FastAPI(title="Interview Q&A Agent", version="1.0.0")

# LLM config — GreenNode MaaS (OpenAI-compatible). On AgentBase Runtime these
# are injected from the runtime env file.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "").strip()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()

SYSTEM_PROMPT = (
    "You are an Interview Q&A coach. The user is preparing for a job interview. "
    "Given an interview question, give a concise, well-structured model answer. "
    "If the question is behavioral, use the STAR method (Situation, Task, Action, "
    "Result). Keep answers under 200 words and practical."
)


class ChatRequest(BaseModel):
    message: str = ""


def _stub_answer(message: str) -> str:
    return f"[stub — set LLM_API_KEY to enable live model] You asked: {message}"


def _call_llm(message: str) -> str:
    """Call the OpenAI-compatible LLM. Tries `openai` SDK, then raw `requests`.

    Raises on transport/API errors so the caller can surface them.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]

    # Preferred path: official OpenAI SDK (OpenAI-compatible base_url).
    try:
        from openai import OpenAI
    except Exception:
        OpenAI = None  # type: ignore

    if OpenAI is not None:
        client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL or None)
        completion = client.chat.completions.create(
            model=LLM_MODEL or "gpt-3.5-turbo",
            messages=messages,
            temperature=0.4,
            max_tokens=600,
        )
        return (completion.choices[0].message.content or "").strip()

    # Fallback path: raw HTTP via requests.
    import requests

    base = (LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": LLM_MODEL or "gpt-3.5-turbo",
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 600,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


@app.get("/health")
def health() -> dict:
    """Health probe required by AgentBase to mark the runtime ACTIVE."""
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Return an interview-style Q&A answer for the posted message."""
    message = (req.message or "").strip()
    if not message:
        return {
            "status": "error",
            "error": "Field 'message' is required.",
            "model": LLM_MODEL or None,
        }

    # No key configured → graceful stub so the app runs without a live model.
    if not LLM_API_KEY:
        return {
            "status": "stub",
            "answer": _stub_answer(message),
            "model": LLM_MODEL or None,
        }

    try:
        answer = _call_llm(message)
        return {"status": "success", "answer": answer, "model": LLM_MODEL or None}
    except Exception as exc:  # degrade gracefully on any LLM/transport error
        return {
            "status": "error",
            "error": f"LLM call failed: {exc}",
            "answer": _stub_answer(message),
            "model": LLM_MODEL or None,
        }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
