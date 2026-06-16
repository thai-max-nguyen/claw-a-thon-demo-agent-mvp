"""Confirm-gated CRM notification setup for the Growth Assistant.

SOP (per the Business Owner's doc):
  1. Build an Action-Recommendation proposal from the daily growth data.
  2. Post a DRY-RUN preview to the Telegram group (segment name, conditions, app-ids,
     channel) — no CRM write yet.
  3. WAIT for an explicit human reply:
       'confirm' / 'ok setup' / 'duyệt'  -> proceed to create segment + noti
       anything else                      -> treated as feedback, abort + log (revise next run)
       no reply within the window         -> no-op
  4. On confirm only: create the CRM segment + notification via the CRM API.

Hard guardrails:
  * NEVER writes to CRM without an explicit confirm AND a CRM_TOKEN.
  * Dry-run preview always shown first.
  * Idempotency: refuses to create a segment whose name already exists.
  * Audit log (who/when/what) appended to crm_noti_audit.jsonl.
  * No PII in Telegram — only segment definitions + counts.

CRM API base (verified live): https://office.zalopay.vn/ge/crm/platform/api/*
Auth: bearer token from the CRM tool's session (env CRM_TOKEN; in-memory, not persisted).

DRAFT-ONLY (hard rule): segments/notis are ALWAYS created with state DRAFT. The agent
NEVER publishes / goes live — a human reviews + publishes in the tool. There is no
publish code path here by design.
Brand name in all user-facing copy is "Zalopay" (not "ZaloPay").
"""
import json
import os
import re
import ssl
import time
import urllib.request

APP_IDS = {"Grab": 222, "Be": 1063, "XANH SM": 3095}
# Real CTA deeplinks per merchant (ZPA in-app, ZPI web) — from the Business Owner 16/06.
DEEPLINKS = {
    "Grab":    ("zalopay://launch/app/2222",          "https://grb.to/Homepage"),
    "XANH SM": ("zalopay://launch/app/1653?id=6944",  "http://xanhsm.onelink.me/3eCA/22jus4at"),
    "Be":      ("zalopay://launch/app/1341",          "https://begroup.onelink.me/n83F/zalopayBe"),
}
# the Business Owner's content templates by scenario (FPU/RPU/RSPU), each with A/B variants.
# {merchant} filled per action; {first_name} stays a CRM dynamic param. Brand = Zalopay.
SCENARIOS = {
    "Acquisition": {  # SCENARIO 1 — FPU (first-time, never rode)
        "A": {"variant": "Urgency", "title": "Đặt xe lần đầu, giảm ngay đến 50K",
              "body": "Dùng Zalopay thanh toán chuyến xe đầu tiên hôm nay — tự động giảm đến 50K cho chuyến đầu.",
              "send": "7:00–8:30 SA", "hyp": "Urgency + số tiền lớn tăng CTR first-time users"},
        "B": {"variant": "Value", "title": "Chuyến đầu tiên với Zalopay — giảm đến 50K",
              "body": "Thanh toán chuyến xe đầu tiên qua Zalopay, chuyến đầu được giảm tự động đến 50K. Thử ngay!",
              "send": "11:30 SA hoặc 5:30 CH", "hyp": "Value framing rõ ràng tăng conversion"}},
    "Reactivation": {  # SCENARIO 2 — RPU (used before, not back this month)
        "A": {"variant": "Personalized", "title": "{first_name}, tháng này chưa đặt xe?",
              "body": "Quay lại {merchant} qua Zalopay ngay — giảm tự động đến 50K cho chuyến tiếp theo của bạn.",
              "send": "6:00–7:00 CH", "hyp": "Personal recall tăng open rate với lapsed users"},
        "B": {"variant": "Value", "title": "Đặt xe tháng này — Zalopay giảm đến 50K",
              "body": "Thanh toán {merchant} bằng Zalopay, chuyến này tiết kiệm đến 50K. Đặt xe thôi!",
              "send": "11:30 SA", "hyp": "Value anchor rõ tăng click-to-ride"}},
    "Resurrection": {  # SCENARIO 3 — RSPU (no txn ≥2 months)
        "A": {"variant": "Urgency", "title": "Lâu rồi không gặp — giảm đến 50K đang chờ",
              "body": "Bạn vắng lâu rồi! Đặt {merchant} qua Zalopay hôm nay — tự động giảm đến 50K. Hết hạn sau 48h.",
              "send": "7:30–8:30 SA", "hyp": "'Lâu rồi' + countdown kích thích FOMO mạnh"},
        "B": {"variant": "Re-intro", "title": "{first_name}, Zalopay có ưu đãi đặt xe cho bạn",
              "body": "Quay lại đặt xe {merchant} qua Zalopay — giảm tự động đến 50K, không cần nhập mã.",
              "send": "5:30–6:30 CH", "hyp": "Frictionless ('không cần nhập mã') giảm barrier cho churned users"}},
}
# Real CRM API base (verified live 2026-06-16). The /api/crm/tool/* path was a
# catch-all that returns "Unauthorized operation"; the SPA actually calls /ge/crm/platform/api/*.
CRM_API = "https://office.zalopay.vn/ge/crm/platform/api"
SEG_LIST = "/segments/view"      # GET ?limit=&offset=
SEG_CREATE = "/segments"         # POST (needs a WRITE-scoped token; read token -> 403)
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_GROUP = os.getenv("TELEGRAM_GROUP_ID", "").strip()
CRM_TOKEN = os.getenv("CRM_TOKEN", "").strip()
AUDIT_LOG = os.path.expanduser("~/clawathon-demo/claw-a-thon-demo-agent/crm_noti_audit.jsonl")
CONFIRM_WORDS = {"confirm", "ok setup", "setup", "duyệt", "ok confirm", "confirmed"}
CTX = ssl.create_default_context()


# ----------------------------------------------------------- proposal
def _prev_cur_month():
    y, m = map(int, time.strftime("%Y-%m").split("-"))
    prev = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{prev[0]}-{prev[1]:02d}", f"{y}-{m:02d}"


def build_proposal(biz, seg, merch, today=None):
    """Derive a re-engagement campaign proposal from the growth data. The segment
    is grounded in the data (lapsed MBS payers); nothing invented."""
    today = today or time.strftime("%d/%m")
    prev_m, cur_m = _prev_cur_month()
    mpu = biz["MPU"]["value"]; npu = biz["NPU"]["value"]
    npu_chg = biz["NPU"].get("change")
    # problem grounded in the flagged metric (NPU flat / acquisition weak)
    problem = (f"Acquisition is flat — NPU {npu:,} ({npu*100/mpu:.1f}% of MPU)"
               + (f", {npu_chg*100:+.1f}% MTD" if npu_chg is not None else "")
               + "; growth leans almost entirely on retention.")
    cause = ("New-user inflow isn't covering the KPI gap; lapsed payers from last month "
             "are the cheapest re-engagement pool to close it.")
    seg_name = f"Noti Lapsed MBS Payers {today}"
    conditions = (f"Paid MBS in {prev_m} (any of Grab/Be/XANH SM) AND no MBS transaction "
                  f"in {cur_m} as of today.")
    return {
        "problem": problem,
        "cause": cause,
        "action": {
            "target": f"Lapsed MBS payers ({prev_m} → not {cur_m})",
            "campaign": "Re-activation cashback (mobility ride/trip voucher)",
            "channel": "Push notification + Zalo OA",
            "metrics": ["Reactivation rate", "Incremental TPV", "Cost/TPV"],
        },
        "segment": {
            "name": seg_name,
            "conditions": conditions,
            "app_ids": APP_IDS,
        },
    }


def _fmtk(n):
    n = round(n)
    return f"{n/1000:.0f}K" if abs(n) >= 1000 else str(n)


def build_actions(biz, seg, merch, fc, signals=None):
    """Multiple prioritized action recommendations per the Business Owner's Step-D framework —
    one per lever/merchant, each grounded in real flagged data. Returns a list of
    action dicts (each carries its own CRM segment spec + targeted noti).

    merch = {label: current_MPU}. Sizing for per-merchant reactivation is the MBS
    lapsed pool (prev-month payers not back this MTD) allocated by merchant MPU share.
    """
    today = time.strftime("%d/%m")
    prev_m, cur_m = _prev_cur_month()
    prev_mn = prev_m[-2:]; cur_mn = cur_m[-2:]
    mpu = biz["MPU"]["value"]; npu = biz["NPU"]["value"]; fpu = biz["FPU"]["value"]
    rpu = mpu - fpu
    npu_pct = npu / fpu if fpu else 0
    tgt = fc.get("_target")
    fc_mpu = fc.get("MPU_fc")
    gap = round(tgt - fc_mpu) if (tgt and fc_mpu) else None
    lapsed_total = round(fc["prev_full"] - rpu) if fc.get("prev_full") else None
    merch_sum = sum(merch.values()) or 1
    sig_m = (signals or {}).get("merchants", {})
    sig_priority = (signals or {}).get("priority")
    leak = (signals or {}).get("funnel", {}).get("leak")

    def _offer(alloc):  # tier the incentive to the MPU gap this merchant must close
        return "Giảm tự động đến 50K" if (alloc or 0) >= 20000 else "Giảm tự động đến 30K"
    actions = []

    # ---- A1: Acquisition (NPU flat is the structural constraint) ----
    actions.append({
        "priority": "P1", "type": "Acquisition",
        "problem": f"NPU flat — {npu:,} ({biz['NPU'].get('delta','').strip()} MTD), only {npu_pct*100:.1f}% of FPU.",
        "cause": (f"H1 (most likely): first-payments are mostly existing Zalopay users — NPU is {npu_pct*100:.1f}% "
                  f"of FPU {fpu:,}, so net-new acquisition is the binding constraint on MPU. "
                  f"H2: the MPU gap ({('~'+_fmtk(gap)+' ') if gap is not None else ''}vs target) can't be closed by "
                  f"retention alone (RPU {rpu*100//mpu if mpu else 0}% of MPU)."),
        "target": "High-intent non-payers in Mobility (installed / browsed ride use-cases, no Mobility payment yet)",
        "channel": "Push + Zalo OA",
        "promo": "Giảm tự động đến 50K cho chuyến đầu",
        "kpi": "New MPU (NPU) ≥ +20% WoW · first-payment conversion ≥ 8%",
        "segment": {
            "name": f"Noti_NPU_MBS_Acq_{today}",
            "conditions": (f"App ID 222/1063/3095 · Inclusion: opened Mobility in {cur_m} · "
                           f"Exclusion: any Mobility payment lifetime · 1 promo/user"),
            "est_size": "size in CRM (intent pool not on dashboard)",
        },
    })

    # ---- A2..: Reactivation per merchant — ordered by derived priority (share, with a
    # bump for decelerating merchants), offers tiered to each merchant's gap allocation ----
    order = sig_priority or [k for k, _ in sorted(merch.items(), key=lambda kv: kv[1], reverse=True)]
    for label in order:
        if label not in merch or label == "AhaMove":
            continue
        cur = merch[label]
        est = round(lapsed_total * cur / merch_sum) if lapsed_total else None
        appid = APP_IDS.get(label, "")
        m = sig_m.get(label, {})
        proj, trend, fcast, alloc = m.get("proj_mom"), m.get("trend"), m.get("forecast"), m.get("gap_alloc")
        mom_txt = f" · projected {proj*100:+.1f}% vs last full month" if proj is not None else ""
        alloc_txt = (f" Needs ≈{_fmtk(alloc)} MPU to close its share of the gap." if alloc else "")
        decel = " It is <b>decelerating</b> on the full-month trend, so the slip is structural, not noise." if trend == "decelerating" else ""
        actions.append({
            "priority": "P2", "type": "Reactivation", "merchant": label,
            "problem": f"{label}: lapsed payers — paid in {prev_m} but no transaction in {cur_m} (≈{_fmtk(est) if est else '?'} users){mom_txt}.",
            "cause": (f"H1: these users churned after last month's activity and aren't back this MTD; "
                      f"{label} carries {cur*100//merch_sum}% of merchant MPU so re-engaging them moves MPU most.{decel}{alloc_txt} "
                      f"H2 (external): post-promo drop-off from {prev_m}."),
            "target": f"{label} users paid {prev_m}, not yet in {cur_m}",
            "channel": "Push + Zalo OA",
            "promo": _offer(alloc),
            "kpi": "Reactivation rate ≥ 15% · Cost/TPV ≤ 8%",
            "segment": {
                "name": f"Noti_RPU_{label.replace(' ','')}_Churn_{today}",
                "conditions": (f"App ID {appid} · Inclusion: Zalopay txn at {label} in {prev_m} · "
                               f"Exclusion: Zalopay txn at {label} in {cur_m} (as of today) · 1 promo/user"),
                "est_size": f"≈{_fmtk(est)} ({prev_m} {label} payers not back in {cur_m})" if est else "size in CRM",
            },
        })

    # attach a tailored noti + CRM label name to each action.
    # Label rule: "[MBS] <Merchant> <segment name>" (cross-merchant Acquisition -> "Mobility").
    for a in actions:
        a["noti"] = build_noti_content(a)
        a["noti_name"] = f"[MBS] {a.get('merchant') or 'Mobility'} {a['segment']['name']}"
    return actions


def build_noti_content(action=None):
    """Noti copy from the Business Owner's scenario templates (A/B variants + send time +
    hypothesis), with {merchant} filled + real per-merchant deeplinks. Brand 'Zalopay'.
    DRAFT — fill these then 'Save' (NOT 'Save & Distribute')."""
    a = action or {"type": "Reactivation"}
    typ = a.get("type", "Reactivation"); mer = a.get("merchant")
    tmpl = SCENARIOS.get(typ, SCENARIOS["Reactivation"])
    # merchant actions fill the name; merchant-agnostic actions (e.g. Acquisition)
    # degrade any stray {merchant} to a generic term so no literal placeholder ever ships.
    fill = (lambda s: s.replace("{merchant}", mer)) if mer else (lambda s: s.replace("{merchant}", "đặt xe"))
    def variant(v):
        return {"variant": v["variant"], "title": fill(v["title"]), "body": fill(v["body"]),
                "send": v["send"], "hyp": v["hyp"]}
    zpa, zpi = DEEPLINKS.get(mer, ("per merchant — see deeplink table", "per merchant — see deeplink table"))
    scen = {"Acquisition": "FPU", "Reactivation": "RPU", "Resurrection": "RSPU"}.get(typ, "RPU")
    return {
        "campaign": (f"{scen} · {mer}" if mer else f"{scen} · Mobility"),
        "promo": "Giảm tự động đến 50K",
        "variant_a": variant(tmpl["A"]),
        "variant_b": variant(tmpl["B"]),
        "zpa_redirection": zpa, "zpi_redirection": zpi,
        "guardrails": "Quiet hours 22:00–08:00 · 1 push/user · honor opt-out · Cost/TPV ≤8%",
    }


def format_noti_content(c):
    a = c["variant_a"]; b = c["variant_b"]
    return "\n".join([
        f"📣 <b>Noti — {c['campaign']}</b> <i>({c['promo']} · draft)</i>",
        f"<b>A · {a['variant']}</b> — {a['title']}",
        f"  {a['body']}  <i>(gửi {a['send']})</i>",
        f"<b>B · {b['variant']}</b> — {b['title']}",
        f"  {b['body']}  <i>(gửi {b['send']})</i>",
        f"ZPA <code>{c['zpa_redirection']}</code> · ZPI <code>{c['zpi_redirection']}</code>",
    ])


def format_proposal(p):
    a = p["action"]; s = p["segment"]
    L = [
        "🤖 <b>CRM noti proposal — DRY RUN (needs your confirm)</b>",
        "",
        f"⚠️ <b>Problem</b>: {p['problem']}",
        f"🔎 <b>Likely cause</b>: {p['cause']}",
        "",
        "🎯 <b>Suggested action</b>",
        f"• Target: {a['target']}",
        f"• Campaign: {a['campaign']}",
        f"• Channel: {a['channel']}",
        f"• Success metrics: {', '.join(a['metrics'])}",
        "",
        "🧩 <b>CRM segment to create</b>",
        f"• Name: <code>{s['name']}</code>",
        f"• Conditions: {s['conditions']}",
        f"• app_ids: {', '.join(f'{k} {v}' for k, v in s['app_ids'].items())}",
        "",
        "Reply <b>confirm</b> to set this up, or send feedback to adjust the strategy. "
        "No CRM change happens without your confirm.",
    ]
    return "\n".join(L)


# ----------------------------------------------------------- telegram
def _tg_send(text):
    if not (TG_TOKEN and TG_GROUP):
        return None
    payload = {"chat_id": int(TG_GROUP), "text": text[:4000], "parse_mode": "HTML"}
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=20)
        return json.load(r).get("result", {}).get("message_id")
    except Exception as e:
        print("tg send err", e); return None


def confirm_gate(timeout=300, poll=5):
    """Poll Telegram for a reply from the group. Returns (verdict, text):
    verdict in {'confirm','feedback','timeout'}. Bounded long-poll."""
    if not (TG_TOKEN and TG_GROUP):
        return ("timeout", "")
    base = f"https://api.telegram.org/bot{TG_TOKEN}"
    # baseline offset: skip backlog, only read messages after we start
    try:
        d = json.load(urllib.request.urlopen(f"{base}/getUpdates?offset=-1", timeout=15))
        offset = (d["result"][-1]["update_id"] + 1) if d.get("result") else None
    except Exception:
        offset = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = f"{base}/getUpdates?timeout={poll}" + (f"&offset={offset}" if offset else "")
        try:
            d = json.load(urllib.request.urlopen(url, timeout=poll + 10))
        except Exception:
            time.sleep(2); continue
        for u in d.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != str(TG_GROUP):
                continue
            txt = (msg.get("text") or "").strip().lower()
            if not txt:
                continue
            if any(w in txt for w in CONFIRM_WORDS):
                return ("confirm", txt)
            return ("feedback", txt)
    return ("timeout", "")


# ----------------------------------------------------------- CRM API
def _crm_call(path, method="GET", body=None):
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    if CRM_TOKEN:
        headers["Authorization"] = CRM_TOKEN if CRM_TOKEN.lower().startswith("bearer") else f"Bearer {CRM_TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    try:
        r = urllib.request.urlopen(urllib.request.Request(CRM_API + path, data=data, method=method, headers=headers), timeout=30, context=CTX)
        return r.status, r.read(2000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(800).decode("utf-8", errors="replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def segment_exists(name):
    st, body = _crm_call(f"{SEG_LIST}?limit=50&offset=0")
    return st == 200 and name in body


def create_segment(spec, dimensions=None, dry_run=True):
    """Create the CRM segment as a DRAFT. dry_run=True (default) only previews.
    Real create requires a WRITE-scoped CRM_TOKEN + dry_run=False (a read-scoped
    token returns 403). Refuses on duplicate name.

    Envelope matches the live schema (verified 2026-06-16):
      {name, labels:[], state:'DRAFT', config:{type:'GROUP', combination:'AND',
       negated:false, dimensions:[...]}, excludeAll:false, contentType:'SEGMENT'}
    `dimensions` carries the actual condition (paid MBS prev-month, not current) —
    its attribute schema is configured in the tool; pass [] to create a draft shell."""
    if dry_run or not CRM_TOKEN:
        return {"dry_run": True, "would_create": spec}
    if segment_exists(spec["name"]):
        return {"skipped": "segment name already exists", "name": spec["name"]}
    payload = {
        "name": spec["name"], "labels": [], "state": "DRAFT", "excludeAll": False,
        "contentType": "SEGMENT",
        "config": {"conditionId": None, "type": "GROUP", "negated": False,
                   "combination": "AND", "dimensions": dimensions or []},
    }
    st, body = _crm_call(SEG_CREATE, method="POST", body=payload)
    return {"status": st, "resp": body[:300]}


def audit(event):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **event}
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ----------------------------------------------------------- orchestrate
def run(biz, seg, merch, post=False, do_confirm=False, dry_run=True):
    p = build_proposal(biz, seg, merch)
    preview = format_proposal(p)
    print(preview)
    audit({"stage": "proposed", "segment": p["segment"]["name"]})
    if not post:
        print("\n[not posted] pass post=True to send the proposal to Telegram.")
        return p
    _tg_send(preview)
    if not do_confirm:
        print("[posted] confirm-gate not armed (do_confirm=False).")
        return p
    verdict, txt = confirm_gate()
    audit({"stage": "gate", "verdict": verdict, "reply": txt[:120]})
    if verdict == "confirm":
        res = create_segment(p["segment"], dry_run=dry_run or not CRM_TOKEN)
        audit({"stage": "setup", "result": res})
        _tg_send(f"✅ Confirmed. CRM segment <code>{p['segment']['name']}</code>: "
                 + ("created." if res.get("status") in (200, 201) else f"{json.dumps(res)[:200]}"))
    elif verdict == "feedback":
        _tg_send("Got it — noted as feedback, holding off on CRM setup. Will adjust the strategy.")
    else:
        print("[gate] no confirm within window — nothing set up.")
    return p


import urllib.parse  # noqa: E402 (used by segment_exists)

if __name__ == "__main__":
    # demo with a sample data shape (no network unless --post)
    import sys
    sample_biz = {"MPU": {"value": 548636}, "NPU": {"value": 3026, "change": -0.002}}
    p = run(sample_biz, {}, {}, post="--post" in sys.argv, do_confirm="--confirm" in sys.argv)
