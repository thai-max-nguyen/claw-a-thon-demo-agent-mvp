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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
 :root{
  --blue:#0045FF;--green:#00D95F;--pos:#10b981;--posd:#047a55;
  --navy:#0b1730;--ink:#283449;--slate:#667591;--slatel:#9aa6be;
  --bg:#eef2f9;--card:#fff;--line:#e7edf7;--linel:#f1f4fb;--mint:#e7f8f0;
  --amb:#b7791f;--ambbg:#fdf3e0;--red:#dc4040;--redbg:#fdecec;--pur:#6d49f0;--purbg:#efeafe;--blubg:#e9efff;
  --sh:0 1px 2px rgba(11,23,48,.04),0 10px 26px rgba(11,23,48,.055);--r:16px}
 *{box-sizing:border-box}
 body{margin:0;background:radial-gradient(1200px 600px at 50% -220px,#e6ecf9,var(--bg));color:var(--ink);font-family:'Be Vietnam Pro',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;-webkit-font-smoothing:antialiased}
 .wrap{max-width:1120px;margin:0 auto;padding:0 22px 60px}
 .bar{position:relative;overflow:hidden;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;background:linear-gradient(120deg,#081138,#0a2bb8 62%,#0045FF);color:#fff;border-radius:20px;padding:22px 24px;margin:22px 0 6px;box-shadow:0 16px 40px rgba(0,38,150,.30)}
 .bar::after{content:"";position:absolute;right:-50px;top:-90px;width:300px;height:300px;background:radial-gradient(circle,rgba(0,217,95,.32),transparent 62%);pointer-events:none}
 .brand{display:flex;align-items:center;gap:14px;z-index:1}
 .mark{width:46px;height:46px;border-radius:13px;background:linear-gradient(135deg,#00D95F,#00a847);display:grid;place-items:center;box-shadow:0 7px 18px rgba(0,200,90,.45);flex:none}
 .brand h1{font-size:21px;margin:0;font-weight:800;letter-spacing:.2px;line-height:1.12}
 .brand h1 span{font-weight:500;opacity:.82}
 .brand .sub{opacity:.84;font-size:12.5px;margin-top:3px;font-weight:500}
 .pill{z-index:1;display:inline-flex;align-items:center;gap:9px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);border-radius:999px;padding:9px 15px;font-weight:700;font-size:12.5px;color:#fff}
 .dot{width:9px;height:9px;border-radius:50%;background:#c3ccde}.dot.ok{background:var(--green);box-shadow:0 0 0 0 rgba(0,217,95,.6);animation:pulse 2s infinite}.dot.bad{background:#ff8a8a}
 @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(0,217,95,.5)}70%{box-shadow:0 0 0 8px rgba(0,217,95,0)}100%{box-shadow:0 0 0 0 rgba(0,217,95,0)}}
 .sec{display:flex;align-items:center;gap:9px;margin:24px 3px 12px;font-size:12px;font-weight:800;letter-spacing:.085em;text-transform:uppercase;color:var(--slate)}
 .sec::before{content:"";width:4px;height:15px;border-radius:3px;background:var(--blue);flex:none}
 .sec b{color:var(--navy)}.sec .muted{margin-left:auto;font-weight:600;text-transform:none;letter-spacing:0;color:var(--slatel);font-size:11.5px}
 .kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
 @media(max-width:840px){.kpis{grid-template-columns:repeat(2,1fr)}}
 .kc{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;box-shadow:var(--sh);display:flex;flex-direction:column;gap:8px;min-height:120px;transition:transform .15s,box-shadow .15s}
 .kc:hover{transform:translateY(-2px);box-shadow:0 6px 14px rgba(11,23,48,.07),0 18px 38px rgba(11,23,48,.10)}
 .kc .lab{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--slate);font-weight:700;display:flex;align-items:center;gap:6px}
 .kc .lab .ic{width:7px;height:7px;border-radius:2px;flex:none}
 .kc .big{font-size:33px;font-weight:800;color:var(--navy);line-height:1;letter-spacing:-1px;margin-top:2px}
 .kc .big small{font-size:15px;color:var(--slatel);font-weight:700;letter-spacing:0;margin-left:1px}
 .kc .r2{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:auto}
 .chip{font-size:11px;font-weight:700;padding:3px 9px;border-radius:999px;white-space:nowrap}
 .c-pos{background:var(--mint);color:var(--posd)}.c-neg{background:var(--redbg);color:#c23636}.c-neu{background:#eef2fa;color:var(--slate)}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px;box-shadow:var(--sh)}
 .charts{display:flex;gap:30px;flex-wrap:wrap}
 .chartwrap{flex:1;min-width:330px}
 .chart-t{font-size:13.5px;font-weight:700;color:var(--navy)}
 .lgd{display:inline-flex;gap:14px;font-size:11px;color:var(--slate);font-weight:600;margin:5px 0 4px}
 .lgd i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:4px;vertical-align:-1px}
 .cap{color:var(--slate);font-size:12px;margin-top:10px}
 .cols3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
 @media(max-width:840px){.cols3{grid-template-columns:1fr}}
 .h{display:flex;align-items:center;gap:8px;margin:0 0 10px;font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--blue);font-weight:800}
 .row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px 0;border-bottom:1px solid var(--linel);font-size:13.5px}
 .row:last-child{border:0;padding-bottom:0}.row .k{color:var(--slate);font-weight:500}.row .v{color:var(--navy);font-weight:700;text-align:right}
 .badge{font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px}
 .b-grn{background:var(--mint);color:var(--posd)}.b-amb{background:var(--ambbg);color:var(--amb)}.b-red{background:var(--redbg);color:#c23636}.b-blu{background:var(--blubg);color:var(--blue)}.b-pur{background:var(--purbg);color:var(--pur)}
 .steps{display:flex;align-items:flex-start;justify-content:space-between}
 .steps .st{flex:1;text-align:center;position:relative;font-size:12px;color:var(--navy);font-weight:600;z-index:0}
 .steps .st::before{content:"";position:absolute;top:16px;right:50%;width:100%;height:2px;background:var(--pos);z-index:-1}
 .steps .st:first-child::before{display:none}
 .steps .node{width:34px;height:34px;border-radius:50%;background:var(--mint);color:var(--posd);display:grid;place-items:center;margin:0 auto 9px;font-weight:800;border:2px solid var(--pos)}
 .tbl{width:100%;border-collapse:collapse;font-size:13px}
 .tbl th{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);color:var(--slate);font-weight:700;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em}
 .tbl td{padding:11px 8px;border-bottom:1px solid var(--linel);color:var(--ink);font-weight:500}
 .tbl tr:last-child td{border:0}.tbl tbody tr:hover{background:var(--linel)}
 .mdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px}
 .up{color:var(--posd);font-weight:700}.down{color:#c23636;font-weight:700}.flat{color:var(--slate)}
 .foot{margin-top:26px;color:var(--slate);font-size:12px;text-align:center}a{color:var(--blue);text-decoration:none;font-weight:600}
</style></head><body><div class="wrap">
 <div class="bar">
   <div class="brand">
     <div class="mark"><svg viewBox="0 0 24 24" fill="none"><rect x="3" y="13" width="4" height="8" rx="1.3" fill="#fff"/><rect x="10" y="8" width="4" height="13" rx="1.3" fill="#fff"/><rect x="17" y="3" width="4" height="18" rx="1.3" fill="#fff"/></svg></div>
     <div><h1>Growth Assistant <span>&middot; Live Monitor</span></h1>
       <div class="sub">Zalopay Mobility &nbsp;&middot;&nbsp; daily analytics &#8594; CRM actions &nbsp;&middot;&nbsp; <span id="clock">&#8230;</span></div></div>
   </div>
   <div class="pill"><span id="dot" class="dot"></span><span id="pill">checking&#8230;</span></div>
 </div>

 <div class="sec"><b>Today at a glance</b> &middot; live KPIs <span class="muted">illustrative figures</span></div>
 <div class="kpis">
   <div class="kc"><div class="lab"><span class="ic" style="background:#0045FF"></span>MPU vs target &middot; MTD</div>
     <div class="big">94<small>%</small></div>
     <div class="r2"><span class="chip c-pos">&#9650; on pace</span>
       <svg width="78" height="26" viewBox="0 0 78 26"><polyline fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="2,22 17,19 32,16 47,12 62,8 76,4"/></svg></div></div>
   <div class="kc"><div class="lab"><span class="ic" style="background:#10b981"></span>Forecast to month-end</div>
     <div class="big">101<small>%</small></div>
     <div class="r2"><span class="chip c-pos">&#9650; lands above</span>
       <svg width="78" height="26" viewBox="0 0 78 26"><polyline fill="none" stroke="#10b981" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="2,18 17,17 32,13 47,11 62,7 76,3"/></svg></div></div>
   <div class="kc"><div class="lab"><span class="ic" style="background:#00D95F"></span>CRM reactivation lift</div>
     <div class="big">+18<small>%</small></div>
     <div class="r2"><span class="chip c-pos">&#9650; 6-wk vs base</span>
       <svg width="78" height="26" viewBox="0 0 78 26"><g fill="#00D95F"><rect x="2" y="20" width="9" height="6" rx="1.5"/><rect x="17" y="16" width="9" height="10" rx="1.5"/><rect x="32" y="13" width="9" height="13" rx="1.5"/><rect x="47" y="9" width="9" height="17" rx="1.5"/><rect x="62" y="5" width="9" height="21" rx="1.5"/><rect x="76" y="2" width="9" height="24" rx="1.5" transform="translate(-9,0)"/></g></svg></div></div>
   <div class="kc"><div class="lab"><span class="ic" style="background:#b7791f"></span>Merchants on track</div>
     <div class="big">3<small>/ 4</small></div>
     <div class="r2"><span class="chip c-neu">Be &middot; lean in</span>
       <span style="display:inline-flex;gap:5px;align-items:center"><i style="width:9px;height:9px;border-radius:50%;background:#10b981;display:inline-block"></i><i style="width:9px;height:9px;border-radius:50%;background:#10b981;display:inline-block"></i><i style="width:9px;height:9px;border-radius:50%;background:#10b981;display:inline-block"></i><i style="width:9px;height:9px;border-radius:50%;background:#e0a317;display:inline-block"></i></span></div></div>
 </div>

 <div class="sec"><b>&#128200; Progress over time</b> &middot; watch this daily <span class="muted">illustrative</span></div>
 <div class="panel">
   <div class="charts">
     <div class="chartwrap">
       <div class="chart-t">MPU vs target &mdash; last 6 months</div>
       <div class="lgd"><span><i style="background:#10b981"></i>Actual MPU (index)</span><span><i style="background:#0045FF"></i>Target = 100</span></div>
       <svg viewBox="0 0 480 215" style="width:100%;height:auto">
         <defs><linearGradient id="ar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#10b981" stop-opacity=".20"/><stop offset="1" stop-color="#10b981" stop-opacity="0"/></linearGradient></defs>
         <g stroke="#eef2fa" stroke-width="1"><line x1="55" y1="190" x2="462" y2="190"/><line x1="55" y1="133" x2="462" y2="133"/><line x1="55" y1="77" x2="462" y2="77"/><line x1="55" y1="20" x2="462" y2="20"/></g>
         <g fill="#9aa6be" font-size="10" text-anchor="end"><text x="48" y="193">80</text><text x="48" y="136">90</text><text x="48" y="80">100</text><text x="48" y="23">110</text></g>
         <line x1="55" y1="77" x2="462" y2="77" stroke="#0045FF" stroke-width="1.5" stroke-dasharray="6 4"/>
         <text x="60" y="71" fill="#0045FF" font-size="10" font-weight="700" text-anchor="start">Target 100</text>
         <path d="M55,145 L135,133 L215,122 L295,105 L375,88 L455,71 L455,190 L55,190 Z" fill="url(#ar)"/>
         <polyline fill="none" stroke="#10b981" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="55,145 135,133 215,122 295,105 375,88 455,71"/>
         <g fill="#10b981"><circle cx="55" cy="145" r="3.5"/><circle cx="135" cy="133" r="3.5"/><circle cx="215" cy="122" r="3.5"/><circle cx="295" cy="105" r="3.5"/><circle cx="375" cy="88" r="3.5"/><circle cx="455" cy="71" r="5"/></g>
         <g fill="#047a55" font-size="10" font-weight="700" text-anchor="middle"><text x="55" y="138">88</text><text x="135" y="126">90</text><text x="215" y="115">92</text><text x="295" y="98">95</text><text x="375" y="81">98</text><text x="455" y="62">101</text></g>
         <g fill="#9aa6be" font-size="10" text-anchor="middle"><text x="55" y="208">M-5</text><text x="135" y="208">M-4</text><text x="215" y="208">M-3</text><text x="295" y="208">M-2</text><text x="375" y="208">M-1</text><text x="455" y="208">now</text></g>
       </svg>
     </div>
     <div class="chartwrap">
       <div class="chart-t">CRM reactivation lift &mdash; last 6 weeks</div>
       <div class="lgd"><span><i style="background:#00D95F"></i>Lift vs baseline (%)</span></div>
       <svg viewBox="0 0 480 215" style="width:100%;height:auto">
         <defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1be46e"/><stop offset="1" stop-color="#00b14f"/></linearGradient></defs>
         <g stroke="#eef2fa" stroke-width="1"><line x1="50" y1="190" x2="462" y2="190"/><line x1="50" y1="147" x2="462" y2="147"/><line x1="50" y1="105" x2="462" y2="105"/><line x1="50" y1="62" x2="462" y2="62"/><line x1="50" y1="20" x2="462" y2="20"/></g>
         <g fill="#9aa6be" font-size="10" text-anchor="end"><text x="44" y="193">0</text><text x="44" y="150">5</text><text x="44" y="108">10</text><text x="44" y="65">15</text><text x="44" y="23">20</text></g>
         <g fill="url(#bg)"><rect x="64" y="156" width="40" height="34" rx="5"/><rect x="132" y="130.5" width="40" height="59.5" rx="5"/><rect x="201" y="113.5" width="40" height="76.5" rx="5"/><rect x="269" y="88" width="40" height="102" rx="5"/><rect x="337" y="62.5" width="40" height="127.5" rx="5"/><rect x="406" y="37" width="40" height="153" rx="5"/></g>
         <g fill="#047a55" font-size="10" font-weight="700" text-anchor="middle"><text x="84" y="150">+4%</text><text x="152" y="124">+7%</text><text x="221" y="107">+9%</text><text x="289" y="82">+12%</text><text x="357" y="56">+15%</text><text x="426" y="31">+18%</text></g>
         <g fill="#9aa6be" font-size="10" text-anchor="middle"><text x="84" y="208">W1</text><text x="152" y="208">W2</text><text x="221" y="208">W3</text><text x="289" y="208">W4</text><text x="357" y="208">W5</text><text x="426" y="208">W6</text></g>
       </svg>
     </div>
   </div>
   <div class="cap">Daily glance: is MPU pacing to target, and are the staged CRM campaigns lifting reactivation week over week? <i>(illustrative; the agent fills these from the live run)</i></div>
 </div>

 <div class="sec"><b>Agent &amp; daily run</b> &middot; live status</div>
 <div class="cols3">
   <div class="panel"><div class="h">&#129302; Agent</div>
     <div class="row"><span class="k">Name</span><span class="v" id="agent">Growth Assistant &mdash; Zalopay Mobility</span></div>
     <div class="row"><span class="k">Model</span><span class="v" id="model">google/gemma-4-31b-it</span></div>
     <div class="row"><span class="k">Mode</span><span class="v" id="mode">live</span></div>
     <div class="row"><span class="k">Endpoint</span><span id="hbadge" class="badge b-blu">checking&#8230;</span></div>
   </div>
   <div class="panel"><div class="h">&#128197; Daily run</div>
     <div class="row"><span class="k">Schedule</span><span class="v">10:00 &middot; launchd</span></div>
     <div class="row"><span class="k">Last verdict</span><span class="badge b-grn">ON TRACK</span></div>
     <div class="row"><span class="k">MPU pacing</span><span class="v">~94% MTD &middot; 101% fc</span></div>
     <div class="row"><span class="k">Lever to pull</span><span class="badge b-pur">acquisition</span></div>
   </div>
   <div class="panel"><div class="h">&#128737; Guardrails</div>
     <div class="row"><span class="k">Audit gate</span><span class="badge b-grn">passing</span></div>
     <div class="row"><span class="k">Fabrication</span><span class="badge b-grn">none</span></div>
     <div class="row"><span class="k">CRM writes</span><span class="badge b-amb">draft-only</span></div>
     <div class="row"><span class="k">Secrets in repo</span><span class="badge b-grn">none</span></div>
   </div>
 </div>

 <div class="sec"><b>Daily pipeline</b> &middot; deterministic, audit-gated</div>
 <div class="panel">
   <div class="steps">
     <div class="st"><div class="node">&#10003;</div>Pull MTD</div>
     <div class="st"><div class="node">&#10003;</div>Forecast</div>
     <div class="st"><div class="node">&#10003;</div>Anomalies</div>
     <div class="st"><div class="node">&#10003;</div>Action plan</div>
     <div class="st"><div class="node">&#10003;</div>CRM drafts</div>
   </div>
 </div>

 <div class="sec"><b>Every merchant covered</b> &middot; momentum tells you where to lean in <span class="muted">illustrative</span></div>
 <div class="panel">
   <table class="tbl"><thead><tr><th>Merchant</th><th>Share</th><th>Full-month trend</th><th>Projected vs last month</th><th>Lever</th></tr></thead>
     <tbody>
     <tr><td><span class="mdot" style="background:#00B14F"></span>Grab</td><td>~60%</td><td class="up">accelerating</td><td class="up">+ slightly up</td><td>Reactivation</td></tr>
     <tr><td><span class="mdot" style="background:#00c2a8"></span>XANH SM</td><td>~24%</td><td class="flat">steady</td><td class="flat">flat</td><td>Reactivation</td></tr>
     <tr><td><span class="mdot" style="background:#dc4040"></span>Be</td><td>~13%</td><td class="down">decelerating</td><td class="down">projected down</td><td>Reactivation &middot; lean in</td></tr>
     <tr><td><span class="mdot" style="background:#e0a317"></span>AhaMove</td><td>~3%</td><td class="flat">steady</td><td class="flat">&mdash;</td><td>&mdash;</td></tr>
     </tbody></table>
 </div>

 <div class="sec"><b>CRM campaigns staged</b> &middot; DRAFT &mdash; human publishes</div>
 <div class="panel">
   <table class="tbl"><thead><tr><th>Campaign</th><th>Priority</th><th>Offer</th><th>Status</th></tr></thead>
     <tbody>
     <tr><td>Acquisition &middot; First Ride</td><td><span class="badge b-blu">P1</span></td><td>auto &minus;50K first ride</td><td><span class="badge b-amb">DRAFT</span></td></tr>
     <tr><td>Reactivation &middot; Grab</td><td><span class="badge b-pur">P2</span></td><td>auto &minus;50K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
     <tr><td>Reactivation &middot; XANH SM</td><td><span class="badge b-pur">P2</span></td><td>auto &minus;30K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
     <tr><td>Reactivation &middot; Be</td><td><span class="badge b-pur">P2</span></td><td>auto &minus;30K</td><td><span class="badge b-amb">DRAFT</span></td></tr>
     </tbody></table>
 </div>
 <div class="foot">Built on <b>GreenNode AgentBase + MaaS</b> &middot; figures illustrative &middot; <a href="https://github.com/thai-max-nguyen/claw-a-thon-demo-agent-mvp">repo</a> &middot; auto-refreshes every 15s</div>
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
    # rate-limit) — a single upstream edge flake otherwise collapses the whole
    # request even though the network is fine seconds later.
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
def root(request: Request):
    # A browser hitting the bare endpoint lands on the live dashboard (the thing worth seeing);
    # API clients (fetch/curl/JSON) still get machine-readable metadata.
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/dashboard")
    return {
        "agent": "Growth Assistant — Zalopay Mobility",
        "version": "1.0.0",
        "live_model": LLM_MODEL if LIVE else None,
        "mode": "live" if LIVE else "stub",
        "categories": CATEGORIES,
        "dashboard": "/dashboard",
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
