"""Interview Q&A Custom Agent — FastAPI app for GreenNode AgentBase.

Full version. Endpoints:
  GET  /health                 -> liveness probe (200)
  GET  /                       -> agent metadata + capabilities
  POST /question               -> generate an interview question (by category/role)
  POST /chat                   -> coaching answer to an interview question
  POST /evaluate               -> score a candidate's answer (0-100) + feedback
  GET  /session/{sid}          -> retrieve a session's Q&A history
  DELETE /session/{sid}        -> clear a session

LLM: OpenAI-compatible (GreenNode MaaS). Configured via env:
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL.
If LLM_API_KEY is empty, every LLM-backed route degrades to a deterministic
stub so the service still boots, /health stays 200, and tests pass with no key.
"""
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or None
LIVE = bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)

CATEGORIES = ["behavioral", "technical", "system-design", "hr"]

app = FastAPI(
    title="Interview Q&A Agent",
    version="1.0.0",
    description="Interview question generation, coaching, and answer scoring on GreenNode AgentBase.",
)

# In-memory session store: {session_id: [{"role","content","ts"}]}
_SESSIONS: dict[str, list[dict]] = {}


# ---------------- LLM call ----------------
def _llm(system: str, user: str, max_tokens: int = 700) -> tuple[str, Optional[str]]:
    """Return (text, model). Falls back to a stub when no key is configured."""
    if not LIVE:
        return (f"[stub — set LLM_API_KEY to enable live model] {user}", None)
    try:
        from openai import OpenAI
        client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
        r = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return (r.choices[0].message.content.strip(), LLM_MODEL)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM upstream error: {type(e).__name__}: {e}")


def _remember(sid: Optional[str], role: str, content: str) -> None:
    if not sid:
        return
    _SESSIONS.setdefault(sid, []).append({"role": role, "content": content, "ts": int(time.time())})


# ---------------- models ----------------
class QuestionReq(BaseModel):
    category: str = Field(default="behavioral", description="behavioral|technical|system-design|hr")
    role: str = Field(default="Product Manager", description="target job role")
    session_id: Optional[str] = None


class ChatReq(BaseModel):
    message: str
    session_id: Optional[str] = None


class EvaluateReq(BaseModel):
    question: str
    answer: str
    session_id: Optional[str] = None


# ---------------- routes ----------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {
        "agent": "Interview Q&A Agent",
        "version": "1.0.0",
        "live_model": LLM_MODEL if LIVE else None,
        "mode": "live" if LIVE else "stub",
        "categories": CATEGORIES,
        "endpoints": ["/health", "/question", "/chat", "/evaluate", "/session/{sid}"],
    }


@app.post("/question")
def question(req: QuestionReq):
    if req.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {CATEGORIES}")
    sid = req.session_id or str(uuid.uuid4())
    sys = ("You are an expert technical interviewer. Generate ONE concise, realistic "
           f"{req.category} interview question for a {req.role} candidate. Question only, no preamble.")
    text, model = _llm(sys, f"Generate one {req.category} question for a {req.role}.", max_tokens=120)
    _remember(sid, "interviewer", text)
    return {"status": "success" if LIVE else "stub", "session_id": sid,
            "category": req.category, "role": req.role, "question": text, "model": model}


@app.post("/chat")
def chat(req: ChatReq):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    sid = req.session_id
    _remember(sid, "candidate", req.message)
    sys = ("You are an interview coach. Give a structured, actionable model answer to the "
           "candidate's interview question. Use the STAR method where relevant and add one short coaching tip.")
    text, model = _llm(sys, req.message)
    _remember(sid, "coach", text)
    return {"status": "success" if LIVE else "stub", "session_id": sid, "answer": text, "model": model}


@app.post("/evaluate")
def evaluate(req: EvaluateReq):
    if not req.question.strip() or not req.answer.strip():
        raise HTTPException(status_code=400, detail="question and answer are required")
    sys = ("You are a strict interview grader. Score the candidate's answer 0-100 and give 2-3 bullet "
           "points of feedback. Start your reply with 'SCORE: <n>/100' on the first line, then the feedback.")
    user = f"Question: {req.question}\n\nCandidate answer: {req.answer}"
    text, model = _llm(sys, user, max_tokens=400)
    score = None
    first = text.splitlines()[0] if text else ""
    if "SCORE:" in first.upper():
        digits = "".join(c for c in first.split(":", 1)[-1] if c.isdigit() or c == "/").split("/")[0]
        score = int(digits) if digits.isdigit() else None
    elif not LIVE:
        score = 0
    _remember(req.session_id, "grader", text)
    return {"status": "success" if LIVE else "stub", "session_id": req.session_id,
            "score": score, "feedback": text, "model": model}


@app.get("/session/{sid}")
def get_session(sid: str):
    if sid not in _SESSIONS:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": sid, "turns": _SESSIONS[sid]}


@app.delete("/session/{sid}")
def clear_session(sid: str):
    existed = _SESSIONS.pop(sid, None) is not None
    return {"session_id": sid, "cleared": existed}
