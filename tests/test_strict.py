"""Strict real-data tests — run against the LIVE GreenNode MaaS model.

Asserts real behavior, not just status codes:
  - /question returns a non-stub, non-empty question
  - /chat returns a substantive coaching answer
  - /evaluate grades a STRONG answer high and a WEAK answer low (real grading)
  - session memory persists across calls
  - validation errors return 400/404
  - telegram router maps commands -> agent calls correctly (via live agent)

Run:  LLM_*=... pytest -q tests/test_strict.py
Requires the live env vars set; skips the grading-spread test in stub mode.
"""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as agentapp  # noqa: E402
import telegram_bot as tg  # noqa: E402

client = TestClient(agentapp.app)
LIVE = agentapp.LIVE


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_root_metadata():
    d = client.get("/").json()
    assert d["mode"] == ("live" if LIVE else "stub")
    assert set(agentapp.CATEGORIES) == {"acquisition", "retention", "forecast", "anomaly"}


def test_root_redirects_browser_to_dashboard():
    # browser (Accept: text/html) -> dashboard; API client (JSON) -> metadata
    r = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code in (307, 308) and r.headers["location"] == "/dashboard"
    j = client.get("/", headers={"accept": "application/json"}).json()
    assert j["dashboard"] == "/dashboard" and j["agent"].startswith("Growth Assistant")


def test_dashboard_serves_html():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    b = r.text
    assert "Growth Assistant" in b and "Live Monitor" in b
    assert "/health" in b and "fetch('/')" in b          # live health/model polling wired
    assert "illustrative" in b.lower()                   # snapshot labeled illustrative
    assert "DRAFT" in b                                  # CRM campaigns panel present
    assert "#0045FF" in b and "#00D95F" in b             # Zalopay brand colors


def test_question_real():
    d = client.post("/question", json={"category": "retention", "merchant": "Grab"}).json()
    assert d["category"] == "retention"
    assert len(d["question"].strip()) > 15
    if LIVE:
        assert d["status"] == "success" and "[stub" not in d["question"]


def test_chat_real():
    d = client.post("/chat", json={"message": "Why is MPU pacing behind target this month?"}).json()
    assert len(d["answer"].strip()) > 30
    if LIVE:
        assert d["status"] == "success" and "[stub" not in d["answer"]


def test_question_bad_category():
    assert client.post("/question", json={"category": "nope"}).status_code == 400


def test_chat_empty():
    assert client.post("/chat", json={"message": "   "}).status_code == 400


def test_evaluate_validation():
    assert client.post("/evaluate", json={"question": "Q?", "answer": ""}).status_code == 400


def test_session_memory():
    sid = f"strict-{uuid.uuid4().hex[:8]}"
    client.post("/question", json={"category": "retention", "merchant": "Grab", "session_id": sid})
    client.post("/chat", json={"message": "Which segment should we reactivate first?", "session_id": sid})
    turns = client.get(f"/session/{sid}").json()["turns"]
    assert len(turns) >= 2
    roles = [t["role"] for t in turns]
    assert "analyst" in roles and "assistant" in roles
    # clear
    assert client.delete(f"/session/{sid}").json()["cleared"] is True
    assert client.get(f"/session/{sid}").status_code == 404


def test_session_missing():
    assert client.get("/session/does-not-exist").status_code == 404


@pytest.mark.skipif(not LIVE, reason="grading spread needs the live model")
def test_evaluate_grading_spread():
    q = "MPU is pacing behind target this month — what's the lever and why?"
    strong = ("Pacing is ~94% MTD but the month-end forecast lands at 101%, so the gap is timing, not demand. "
              "The binding stage is acquisition: new-payers are a small share of first-payments while retention "
              "is steady. Lever: re-engage lapsed riders with a tiered reactivation push (50K where the gap is "
              "largest, 30K elsewhere), and lean harder on Be, which is decelerating MoM.")
    weak = "I don't know, MPU is just low somehow, maybe spend more money everywhere."
    s_strong = client.post("/evaluate", json={"question": q, "answer": strong}).json()["score"]
    s_weak = client.post("/evaluate", json={"question": q, "answer": weak}).json()["score"]
    assert isinstance(s_strong, int) and isinstance(s_weak, int)
    assert s_strong >= 60, f"strong data-backed answer scored too low: {s_strong}"
    assert s_weak <= 40, f"weak answer scored too high: {s_weak}"
    assert s_strong > s_weak


def test_telegram_router_help():
    h = tg.handle_text("/help")
    assert "/run" in h and "/confirm" in h          # MBS Growth Assistant commands
    assert tg.handle_text("just chatter") == ""      # privacy: ignore non-commands


@pytest.mark.skipif(not LIVE, reason="router live calls need the model")
def test_telegram_router_ask_live():
    # router calls the agent over HTTP; point it at the in-process app via monkeypatch
    out = {}

    def fake_post(path, payload):
        return client.post(path, json=payload).json()

    orig = tg.agent_post
    tg.agent_post = fake_post
    try:
        reply = tg.handle_text("/ask What is your greatest weakness?")
        assert len(reply.strip()) > 30 and "[stub" not in reply
        evrep = tg.handle_text("/evaluate Why us? ||| Because I admire the mission and want to grow.")
        assert "Score:" in evrep
    finally:
        tg.agent_post = orig
