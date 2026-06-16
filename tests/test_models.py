"""Model-support tests — prove GreenNode MaaS actually serves the models the agent uses.

The agent is model-agnostic: each role (question/chat/evaluate) resolves to its
MODEL_* env override or falls back to LLM_MODEL. This test reads that real config
and verifies every distinct model it resolves to returns a real completion
(HTTP 200 + non-empty content) and appears in the catalog. If GreenNode grants or
revokes a model, this catches it — no hardcoded model list to drift out of date.

Run:  LLM_*=... pytest -q tests/test_models.py
Skipped entirely in stub mode (no API key).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as agentapp  # noqa: E402

# The distinct models the app is actually configured to use (per-role + fallback).
ASSIGNED_MODELS = sorted({m for m in (
    agentapp.MODEL_QUESTION, agentapp.MODEL_CHAT, agentapp.MODEL_EVALUATE, agentapp.LLM_MODEL
) if m})

pytestmark = pytest.mark.skipif(not agentapp.LIVE, reason="model probes need a live API key")


def _complete(model: str) -> str:
    from openai import OpenAI
    client = OpenAI(base_url=agentapp.LLM_BASE_URL, api_key=agentapp.LLM_API_KEY)
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with the single word: OK"}],
        max_tokens=256,
        temperature=0,
    )
    return (r.choices[0].message.content or "").strip()


@pytest.mark.parametrize("model", ASSIGNED_MODELS)
def test_model_supported(model):
    """Each assigned model must return a non-empty completion (GreenNode serves it)."""
    out = _complete(model)
    assert out, f"{model} returned empty content"


def test_assigned_models_in_catalog():
    """All assigned models appear in GreenNode's /models catalog."""
    import urllib.request, json
    r = urllib.request.Request(agentapp.LLM_BASE_URL + "/models",
                               headers={"Authorization": "Bearer " + agentapp.LLM_API_KEY})
    catalog = {m["id"] for m in json.loads(urllib.request.urlopen(r, timeout=20).read()).get("data", [])}
    for m in ASSIGNED_MODELS:
        assert m in catalog, f"{m} not in GreenNode catalog"


def test_per_role_models_are_enabled():
    """The per-role models the app is configured with resolve to enabled models."""
    for m in {agentapp.MODEL_QUESTION, agentapp.MODEL_CHAT, agentapp.MODEL_EVALUATE}:
        if not m:
            continue
        assert _complete(m), f"configured role model not served: {m}"
