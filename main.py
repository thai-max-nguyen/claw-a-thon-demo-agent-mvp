import os
from datetime import datetime

from dotenv import load_dotenv
from greennode_agentbase import (
    GreenNodeAgentBaseApp,
    RequestContext,
    PingStatus,
)

load_dotenv()

app = GreenNodeAgentBaseApp()

# LLM config — points at GreenNode MaaS (OpenAI-compatible) via env vars.
# On AgentBase Runtime these are injected from the runtime env file.
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")

SYSTEM_PROMPT = (
    "You are an Interview Q&A assistant. The user is preparing for a job "
    "interview. Given a question (and optional role/context), give a concise, "
    "well-structured model answer. If the question is behavioral, use the STAR "
    "method (Situation, Task, Action, Result). Keep answers under 200 words."
)


def _llm_client():
    """Lazily build an OpenAI-compatible client for GreenNode MaaS.

    Returns None if not configured so the agent degrades gracefully
    (health endpoint + structure still work without a live key).
    """
    if not (LLM_API_KEY and LLM_BASE_URL and LLM_MODEL):
        return None
    from openai import OpenAI

    return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Interview Q&A entrypoint (POST /invocations).

    Payload:
        question (str): the interview question (required)
        role (str): optional target role, e.g. "Backend Engineer"
        context (str): optional extra context about the candidate
    """
    question = (payload.get("question") or payload.get("message") or "").strip()
    role = (payload.get("role") or "").strip()
    extra = (payload.get("context") or "").strip()

    if not question:
        return {
            "status": "error",
            "error": "Field 'question' is required.",
            "timestamp": datetime.now().isoformat(),
            "session_id": context.session_id,
        }

    user_msg = question
    if role:
        user_msg = f"Target role: {role}\nQuestion: {question}"
    if extra:
        user_msg += f"\nCandidate context: {extra}"

    client = _llm_client()
    if client is None:
        return {
            "status": "degraded",
            "answer": (
                "LLM not configured (set LLM_MODEL, LLM_API_KEY, LLM_BASE_URL). "
                f"Echoing question: {question}"
            ),
            "model": LLM_MODEL or None,
            "timestamp": datetime.now().isoformat(),
            "session_id": context.session_id,
        }

    completion = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.4,
        max_tokens=600,
    )
    answer = completion.choices[0].message.content

    return {
        "status": "success",
        "answer": answer,
        "model": LLM_MODEL,
        "timestamp": datetime.now().isoformat(),
        "session_id": context.session_id,
    }


@app.ping
def health_check() -> PingStatus:
    """Custom health check for GET /health endpoint."""
    return PingStatus.HEALTHY


if __name__ == "__main__":
    app.run(port=8080, host="0.0.0.0")
