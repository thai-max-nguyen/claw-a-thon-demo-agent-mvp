"""Growth Assistant — Zalopay Mobility · Custom Agent (FastAPI) for GreenNode AgentBase.

Full version. Endpoints:
  GET  /health                 -> liveness probe (200)
  GET  /                       -> agent metadata + capabilities
  POST /question               -> a growth-diagnostic question (by category/merchant)
  POST /chat                   -> growth-analyst answer about Zalopay Mobility metrics/actions
  POST /evaluate               -> score a proposed growth action (0-100) + feedback
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
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip() or None
LIVE = bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)

# Per-role model selection (quality-first). Each role can be pinned to its best
# GreenNode MaaS model; all fall back to LLM_MODEL if unset. Recommended:
#   question -> gemini/gemini-2.5-pro      (crisp question generation)
#   chat     -> openai/gpt-5               (best coaching narrative)
#   evaluate -> qwen/qwen3-235b-a22b-thinking-2507  (rigorous scoring)
MODEL_QUESTION = os.getenv("MODEL_QUESTION", "").strip() or LLM_MODEL
MODEL_CHAT = os.getenv("MODEL_CHAT", "").strip() or LLM_MODEL
MODEL_EVALUATE = os.getenv("MODEL_EVALUATE", "").strip() or LLM_MODEL

CATEGORIES = ["acquisition", "retention", "forecast", "anomaly"]
MERCHANTS = ["Grab", "XANH SM", "Be", "all"]

# Live monitoring dashboard (served at GET /dashboard). Agent health + model are polled
# live from /health and /; the growth snapshot is ILLUSTRATIVE (real numbers stay internal).
_DASHBOARD_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Growth Assistant - Live Monitor - Zalopay</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{--blue:#0045FF;--green:#00D95F;--navy:#0A1F44;--ink:#16224a;--mut:#5b6b8c;--bg:#eef3ff;--card:#fff;--line:#e3e9f7;--mint:#e6fbee;--amb:#f59e0b;--red:#ef4444}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:'Be Vietnam Pro',system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
 .wrap{max-width:1080px;margin:0 auto;padding:0 20px 60px}
 .hero{background:linear-gradient(110deg,var(--blue),#0a2ddd 55%,var(--green));color:#fff;border-radius:0 0 22px 22px;padding:26px 26px 22px;margin:0 -20px 22px;box-shadow:0 12px 30px rgba(0,69,255,.18)}
 .hero .row{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap}
 h1{font-size:24px;margin:0;font-weight:800;letter-spacing:.2px}
 .hero .sub{opacity:.92;font-size:13px;margin-top:4px;font-weight:500}
 .pill{display:inline-flex;align-items:center;gap:8px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.3);border-radius:999px;padding:8px 14px;font-weight:700;font-size:13px;color:#fff}
 .dot{width:9px;height:9px;border-radius:50%;background:#cbd6f5}.dot.ok{background:var(--green);box-shadow:0 0 0 0 rgba(0,217,95,.6);animation:pulse 2s infinite}.dot.bad{background:#ff8a8a}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(0,217,95,.5)}70%{box-shadow:0 0 0 8px rgba(0,217,95,0)}100%{box-shadow:0 0 0 0 rgba(0,217,95,0)}}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 6px 18px rgba(10,31,68,.05)}
 .card h3{margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--blue);font-weight:700}
 .kv{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #eef2fb;font-size:14px}.kv:last-child{border:0}
 .kv b{font-weight:700;color:var(--navy)}.mut{color:var(--mut)}
 .badge{font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px}
 .b-grn{background:var(--mint);color:#0a9b4b}.b-amb{background:#fff6e6;color:#b9760a}.b-red{background:#ffecec;color:#d23a3a}.b-blu{background:#e7eeff;color:var(--blue)}.b-pur{background:#efe9ff;color:#6b3df0}
 .flow{display:flex;gap:8px;flex-wrap:wrap}.step{flex:1;min-width:90px;background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:12px;text-align:center;font-size:12px;color:var(--navy);font-weight:600}
 .step .s{display:block;color:var(--green);font-weight:800;font-size:15px;margin-top:3px}
 table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:9px 6px;border-bottom:1px solid var(--line)}th{color:var(--mut);font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
 td{color:var(--navy)}.up{color:#0a9b4b;font-weight:700}.down{color:#d23a3a;font-weight:700}.flat{color:var(--mut)}
 .foot{margin-top:24px;color:var(--mut);font-size:12px;text-align:center}a{color:var(--blue);text-decoration:none;font-weight:600}
 .full{grid-column:1/-1}
</style></head><body><div class="wrap">
 <div class="hero"><div class="row">
   <div><h1>Growth Assistant <span style="font-weight:600;opacity:.85">- Live Monitor</span></h1>
     <div class="sub">Zalopay Mobility &nbsp;|&nbsp; daily analytics &#8594; CRM actions &nbsp;|&nbsp; <span id="clock"></span></div></div>
   <div class="pill"><span id="dot" class="dot"></span><span id="pill">checking...</span></div>
 </div></div>
 <div class="grid">
   <div class="card full"><h3>&#128200; Business progress &amp; CRM effect &middot; this is what to watch daily &middot; illustrative</h3>
     <div style="display:flex;gap:24px;flex-wrap:wrap">
       <div style="flex:1;min-width:300px">
         <div class="mut" style="font-size:13px;font-weight:700;margin-bottom:6px;color:var(--navy)">MPU vs target &mdash; last 6 months <span style="color:var(--green)">&#9650; on pace</span></div>
         <svg viewBox="0 0 320 145" width="100%" height="150" preserveAspectRatio="none">
           <line x1="8" y1="30" x2="312" y2="30" stroke="#0045FF" stroke-dasharray="5 4" stroke-width="1.5"/>
           <text x="10" y="24" fill="#0045FF" font-size="10" font-weight="700">target</text>
           <polyline fill="none" stroke="#00B14F" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="20,112 78,100 136,88 194,72 252,54 300,42"/>
           <circle cx="300" cy="42" r="4.5" fill="#00B14F"/>
           <g fill="#5b6b8c" font-size="10" text-anchor="middle"><text x="20" y="136">M-5</text><text x="78" y="136">M-4</text><text x="136" y="136">M-3</text><text x="194" y="136">M-2</text><text x="252" y="136">M-1</text><text x="300" y="136">now</text></g>
         </svg>
       </div>
       <div style="flex:1;min-width:300px">
         <div class="mut" style="font-size:13px;font-weight:700;margin-bottom:6px;color:var(--navy)">CRM reactivation lift &mdash; last 6 weeks <span style="color:var(--green)">&#9650; rising</span></div>
         <svg viewBox="0 0 320 145" width="100%" height="150" preserveAspectRatio="none">
           <g fill="#00D95F"><rect x="22" y="96" width="30" height="28" rx="4"/><rect x="70" y="86" width="30" height="38" rx="4"/><rect x="118" y="78" width="30" height="46" rx="4"/><rect x="166" y="64" width="30" height="60" rx="4"/><rect x="214" y="52" width="30" height="72" rx="4"/><rect x="262" y="40" width="30" height="84" rx="4"/></g>
           <g fill="#5b6b8c" font-size="10" text-anchor="middle"><text x="37" y="138">W1</text><text x="85" y="138">W2</text><text x="133" y="138">W3</text><text x="181" y="138">W4</text><text x="229" y="138">W5</text><text x="277" y="138">W6</text></g>
         </svg>
       </div>
     </div>
     <div class="mut" style="font-size:12px;margin-top:8px">Daily glance: is MPU pacing to target, and are the staged CRM campaigns lifting reactivation? <i>(illustrative; the agent fills these from the live run)</i></div>
   </div>
   <div class="card"><h3>Agent</h3>
     <div class="kv"><span class="mut">Name</span><b id="agent">...</b></div>
     <div class="kv"><span class="mut">Model</span><b id="model">...</b></div>
     <div class="kv"><span class="mut">Mode</span><b id="mode">...</b></div>
     <div class="kv"><span class="mut">Endpoint</span><span id="hbadge" class="badge b-blu">...</span></div>
   </div>
   <div class="card"><h3>Daily run</h3>
     <div class="kv"><span class="mut">Schedule</span><b>10:00 &middot; launchd</b></div>
     <div class="kv"><span class="mut">Last verdict</span><span class="badge b-amb">AT RISK</span></div>
     <div class="kv"><span class="mut">MPU pacing</span><b>~95% of target</b></div>
     <div class="kv"><span class="mut">Binding constraint</span><span class="badge b-pur">acquisition</span></div>
   </div>
   <div class="card"><h3>Guardrails</h3>
     <div class="kv"><span class="mut">Audit gate</span><span class="badge b-grn">passing</span></div>
     <div class="kv"><span class="mut">Fabrication</span><span class="badge b-grn">none</span></div>
     <div class="kv"><span class="mut">CRM writes</span><span class="badge b-amb">draft-only</span></div>
     <div class="kv"><span class="mut">Secrets in repo</span><span class="badge b-grn">none</span></div>
   </div>
   <div class="card full"><h3>Pipeline</h3>
     <div class="flow">
       <div class="step">Pull MTD<span class="s">&#10003;</span></div>
       <div class="step">Forecast<span class="s">&#10003;</span></div>
       <div class="step">Anomalies<span class="s">&#10003;</span></div>
       <div class="step">Action plan<span class="s">&#10003;</span></div>
       <div class="step">CRM drafts<span class="s">&#10003;</span></div>
     </div></div>
   <div class="card full"><h3>Every merchant covered &middot; momentum = where to lean in &middot; illustrative</h3>
     <table><tr><th>Merchant</th><th>Share</th><th>Full-month trend</th><th>Projected vs last month</th><th>Lever</th></tr>
       <tr><td>Grab</td><td>~60%</td><td class="up">accelerating</td><td class="up">+ slightly up</td><td>Reactivation</td></tr>
       <tr><td>XANH SM</td><td>~24%</td><td class="flat">steady</td><td class="flat">flat</td><td>Reactivation</td></tr>
       <tr><td>Be</td><td>~13%</td><td class="down">decelerating</td><td class="down">projected down</td><td>Reactivation &middot; lean in</td></tr>
       <tr><td>AhaMove</td><td>~3%</td><td class="flat">steady</td><td class="flat">-</td><td>-</td></tr>
     </table></div>
   <div class="card full"><h3>CRM campaigns staged &middot; DRAFT (human publishes)</h3>
     <table><tr><th>Campaign</th><th>Priority</th><th>Offer</th><th>Status</th></tr>
       <tr><td>Acquisition &middot; First Ride</td><td>P1</td><td>auto -50K first ride</td><td><span class="badge b-amb">DRAFT</span></td></tr>
       <tr><td>Reactivation &middot; Grab</td><td>P2</td><td>auto -50K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
       <tr><td>Reactivation &middot; XANH SM</td><td>P2</td><td>auto -30K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
       <tr><td>Reactivation &middot; Be</td><td>P2</td><td>auto -30K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
     </table></div>
 </div>
 <div class="foot">Built on GreenNode AgentBase + MaaS &middot; figures illustrative &middot; <a href="https://github.com/thai-max-nguyen/claw-a-thon-demo-agent-mvp">repo</a> &middot; auto-refreshes every 15s</div>
</div>
<script>
 function clock(){document.getElementById('clock').textContent='updated '+new Date().toLocaleTimeString()}
 async function info(){try{const d=await (await fetch('/')).json();
   document.getElementById('agent').textContent=d.agent||'-';
   document.getElementById('model').textContent=d.live_model||'(stub)';
   document.getElementById('mode').textContent=d.mode||'-';}catch(e){}}
 async function ping(){const dot=document.getElementById('dot'),p=document.getElementById('pill'),hb=document.getElementById('hbadge');
   try{const r=await fetch('/health');const ok=r.ok&&(await r.json()).status==='ok';
     dot.className='dot '+(ok?'ok':'bad');p.textContent=ok?'LIVE - healthy':'unreachable';
     hb.textContent=ok?'200 OK':'down';hb.className='badge '+(ok?'b-grn':'b-red');}
   catch(e){dot.className='dot bad';p.textContent='unreachable';hb.textContent='down';hb.className='badge b-red'}clock()}
 info();ping();setInterval(ping,15000);
</script></body></html>"""

app = FastAPI(
    title="Growth Assistant — Zalopay Mobility",
    version="1.0.0",
    description="Growth Assistant for Zalopay Mobility — daily growth analytics + CRM action Q&A on GreenNode AgentBase.",
)

# In-memory session store: {session_id: [{"role","content","ts"}]}
_SESSIONS: dict[str, list[dict]] = {}


# ---------------- LLM call ----------------
def _llm(system: str, user: str, max_tokens: int = 700, model: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Return (text, model). Falls back to a stub when no key is configured.
    `model` lets each role pick its quality-tuned model; defaults to LLM_MODEL."""
    use_model = model or LLM_MODEL
    if not LIVE:
        return (f"[stub — set LLM_API_KEY to enable live model] {user}", None)
    from openai import OpenAI, APIConnectionError, APITimeoutError, RateLimitError
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=60)
    # 2-retry exponential backoff on TRANSIENT errors only (connection/timeout/
    # rate-limit). Lesson from reddit_get: a single upstream edge flake otherwise
    # collapses the whole request even though the network is fine seconds later.
    # Non-transient errors (bad model, 4xx) are NOT retried — fail fast as 502.
    last = None
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=use_model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return ((r.choices[0].message.content or "").strip(), use_model)
        except (APIConnectionError, APITimeoutError, RateLimitError) as e:
            last = e
            if attempt < 2:
                time.sleep(3 * (attempt + 1) ** 2)  # 3s, 12s
                continue
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"LLM error: {type(e).__name__}: {e}")
    raise HTTPException(status_code=502, detail=f"LLM upstream unavailable after retries: {type(last).__name__}")


def _remember(sid: Optional[str], role: str, content: str) -> None:
    if not sid:
        return
    _SESSIONS.setdefault(sid, []).append({"role": role, "content": content, "ts": int(time.time())})


# ---------------- models ----------------
class QuestionReq(BaseModel):
    category: str = Field(default="acquisition", description="acquisition|retention|forecast|anomaly")
    merchant: str = Field(default="all", description="Grab | XANH SM | Be | all")
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
        "agent": "Growth Assistant — Zalopay Mobility",
        "version": "1.0.0",
        "live_model": LLM_MODEL if LIVE else None,
        "mode": "live" if LIVE else "stub",
        "categories": CATEGORIES,
        "endpoints": ["/health", "/dashboard", "/question", "/chat", "/evaluate", "/session/{sid}"],
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Live monitoring dashboard — agent health/model (live, polled) + an illustrative
    snapshot of the daily growth pipeline. Self-contained HTML; figures are illustrative."""
    return _DASHBOARD_HTML


@app.post("/question")
def question(req: QuestionReq):
    if req.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"category must be one of {CATEGORIES}")
    sid = req.session_id or str(uuid.uuid4())
    sys = ("You are a senior growth analyst for Zalopay Mobility (MBS). Generate ONE sharp, "
           f"data-driven diagnostic question the growth team should investigate about {req.category} "
           f"for {req.merchant}. Question only, no preamble.")
    text, model = _llm(sys, f"One {req.category} diagnostic question for {req.merchant}.", max_tokens=120, model=MODEL_QUESTION)
    _remember(sid, "analyst", text)
    return {"status": "success" if LIVE else "stub", "session_id": sid,
            "category": req.category, "merchant": req.merchant, "question": text, "model": model}


@app.post("/chat")
def chat(req: ChatReq):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    sid = req.session_id
    _remember(sid, "user", req.message)
    sys = ("You are Growth Assistant, a senior growth analyst for Zalopay Mobility (MBS). Answer the "
           "user's question about mobility growth — MPU/NPU/FPU/RPU metrics, pacing forecasts, anomalies, "
           "merchant segments (Grab/XANH SM/Be), and CRM push-notification actions — concisely and "
           "practically, ending with a concrete recommended next step.")
    text, model = _llm(sys, req.message, model=MODEL_CHAT)
    _remember(sid, "assistant", text)
    return {"status": "success" if LIVE else "stub", "session_id": sid, "answer": text, "model": model}


@app.post("/evaluate")
def evaluate(req: EvaluateReq):
    if not req.question.strip() or not req.answer.strip():
        raise HTTPException(status_code=400, detail="question and answer are required")
    sys = ("You are a senior growth reviewer for Zalopay Mobility. Score the proposed growth answer/action "
           "0-100 on impact, targeting precision, and measurability, then give 2-3 bullet points of feedback. "
           "Start your reply with 'SCORE: <n>/100' on the first line, then the feedback.")
    user = f"Question: {req.question}\n\nProposed growth answer/action: {req.answer}"
    text, model = _llm(sys, user, max_tokens=700, model=MODEL_EVALUATE)
    score = None
    # scan ALL lines for "SCORE: n" — reasoning models may emit preamble first
    import re as _re
    m = _re.search(r"SCORE:\s*(\d{1,3})", text, _re.IGNORECASE)
    if m:
        score = min(int(m.group(1)), 100)
    elif not LIVE:
        score = 0
    _remember(req.session_id, "reviewer", text)
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
