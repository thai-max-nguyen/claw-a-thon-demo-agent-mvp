"""the Business Owner's Growth Assistant — DASHBOARD-ONLY daily flow (no Excel input).

Everything traces to the Atlas (Tableau) dashboards. The only non-dashboard input
is the monthly MPU KPI target, which is a fixed plan number (set once below), not a
daily feed. Reach = MPU / target is computed.

Sources (all live from Atlas):
  MBS totals + MTD ▲ deltas  -> MBS KPI tiles (Trans, TPV*, REV*, Refund*, MPU*, NPU*)
  MBS segment split          -> "Monthly" worksheet (Retained=reals[1], Resurrected=reals[19]),
                                FPU = MPU - NPU - Retained - Resurrected
  MPU by merchant (current)  -> "YTM" worksheet (merchant-major, current month first, stride 13)
  Merchant discount/Cost-TPV -> merchant dashboards (their own trailing window)

NOT available from the dashboards (left out, never fabricated):
  * per-merchant segment split (NPU/FPU/RSPU/RPU by merchant)
  * per-merchant Trans/TPV at MTD (merchant dashboards run a fixed window)
  * full-month forecast (the Business Owner's plan model, not reproducible from the dashboard)

Anomaly tiers (the rules): >=+5% Highlight · 0..+5% Normal · -1..0 Watch · <=-1% Alert.
Cost metrics (Refund) use inverted polarity (a rise is bad).
"""
import os, sys, re, html, json, time, urllib.request, urllib.parse
sys.path.insert(0, os.path.expanduser("~/.config/life-ops"))
import bat_signal as bs

ATLAS_BASE = "https://atlas.vng.com.vn"
SITE = "ZLPDataServices"
COMPARISON = "MTD vs previous MTD"
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_GROUP = os.getenv("TELEGRAM_GROUP_ID", "").strip()
OWNER_PAGE = "335580236"

# Monthly MPU KPI target (from the MBS Growth plan — fixed, not a daily feed).
# ILLUSTRATIVE monthly MPU targets (round placeholders — NOT the real plan). The real
# targets are confidential; set them via your own config/env in a real deployment.
MPU_TARGET = {
    "2026-01": 700000, "2026-02": 720000, "2026-03": 740000, "2026-04": 760000,
    "2026-05": 780000, "2026-06": 800000, "2026-07": 830000, "2026-08": 860000,
    "2026-09": 900000, "2026-10": 940000, "2026-11": 980000, "2026-12": 1020000,
}
YTM_STRIDE = 13  # YTM worksheet: values per merchant (current month first)
MERCH_ORDER = ["Grab", "XANH SM", "Be", "AhaMove"]  # YTM merchant-major order

MERCH_VOL = {
    "Grab": ("GrabMonitoring", "GrabMonitoring",
             {"Transactions": "Transaction", "TPV": "Volume", "Discount": "Discount"}),
    "XANH SM": ("XanhSMMonitoring", "XanhSMMonitoring",
                {"Transactions": "Total Trans", "TPV": "Volume", "Discount": "Discount"}),
    "Be": ("BeMonitoring", "BeMonitoring",
           {"Transactions": "Total Trans", "TPV": "Volume", "Discount": "Discount"}),
}


# ------------------------------------------------------------ Atlas plumbing
def _bootstrap_cols(workbook, view, sheet_id, cookies, timeout=120, allow_big=False):
    """Scoped bootstrap of one worksheet -> list of dataColumns."""
    ch = (f"workgroup_session_id={cookies['workgroup_session_id']}; "
          f"XSRF-TOKEN={cookies['XSRF-TOKEN']}; tableau_locale=en")
    embed = f"{ATLAS_BASE}/t/{SITE}/views/{workbook}/{view}?:embed=yes&:showVizHome=no"
    shell = urllib.request.urlopen(urllib.request.Request(embed, headers={"Cookie": ch}), timeout=30).read().decode()
    m = re.search(r'"sessionid":"([^"]+)"', html.unescape(shell))
    if not m:
        raise RuntimeError("no sessionid (session dead?)")
    sid = m.group(1)
    post = f"{ATLAS_BASE}/vizql/t/{SITE}/w/{workbook}/v/{view}/bootstrapSession/sessions/{sid}"
    req = urllib.request.Request(post, method="POST",
        data=urllib.parse.urlencode({"sheet_id": sheet_id}).encode(),
        headers={"Cookie": ch, "X-Tsi-Active-Tab": sheet_id,
                 "Content-Type": "application/x-www-form-urlencoded", "Accept": "text/javascript"})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="replace")
    if not allow_big and len(raw) > 200_000:
        raise RuntimeError(f"sheet_id {sheet_id!r} not scoped (payload {len(raw)})")
    cols = []
    i = 0
    while i < len(raw):
        mm = re.match(r"(\d+);", raw[i:i + 24])
        if not mm:
            break
        ln = int(mm.group(1)); start = i + mm.end(); chunk = raw[start:start + ln]; i = start + ln
        try:
            j = json.loads(chunk)
        except Exception:
            continue

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "dataSegments" and isinstance(v, dict) and "0" in v:
                        cols.extend(v["0"].get("dataColumns", []))
                    else:
                        walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(j)
    return cols


def bootstrap_tile(workbook, view, sheet_id, cookies, timeout=120):
    """One KPI tile -> (value, delta_str|None)."""
    cols = _bootstrap_cols(workbook, view, sheet_id, cookies, timeout)
    nums, delta = [], None
    for c in cols:
        for dv in c.get("dataValues", []):
            if isinstance(dv, bool):
                continue
            if isinstance(dv, (int, float)):
                nums.append(dv)
            elif isinstance(dv, str) and ("▲" in dv or "▼" in dv):
                delta = dv.strip()
    if not nums:
        raise RuntimeError(f"no numeric in tile {sheet_id!r}")
    return (nums[0] if len(nums) == 1 else max(nums, key=abs)), delta


def _delta_pct(delta):
    if not delta:
        return None
    m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%", delta)
    if not m:
        return None
    v = float(m.group(1)) / 100.0
    return -v if ("▼" in delta and v > 0) else v


# ------------------------------------------------------------ data pulls
def pull_mbs_business(cookies):
    # FPU MBS* tile = "FPU (incl NPU)" per the Business Owner's v27 def (RPU = MPU - FPU incl NPU)
    tiles = {"Transactions": "Trans", "TPV": "TPV*", "Gross Revenue": "REV*",
             "Refund": "Refund*", "MPU": "MPU*", "NPU": "NPU*", "FPU": "FPU MBS*"}
    out = {}
    for metric, sheet in tiles.items():
        val, delta = bootstrap_tile("RSTMonitoring", "MBSMonitoring", sheet, cookies)
        out[metric] = {"value": val, "delta": delta, "change": _delta_pct(delta)}
        print(f"  MBS {metric}: {val} {delta or ''}", flush=True)
        time.sleep(0.3)
    return out


def pull_segments(cookies, mpu, npu):
    """MBS segment split from the 'Monthly' worksheet (segment-major, current
    month first per 18-block). FPU is the residual so the four sum to MPU."""
    cols = _bootstrap_cols("RSTMonitoring", "MBSMonitoring", "Monthly", cookies)
    reals = next((c["dataValues"] for c in cols if c.get("dataType") == "real"), None)
    if not reals or len(reals) < 20:
        raise RuntimeError("Monthly worksheet: real column missing/short")
    retained = int(reals[1]); resurrected = int(reals[19])
    fpu = mpu - npu - retained - resurrected
    return {"NPU": npu, "FPU": fpu, "Resurrected": resurrected, "Retained": retained, "MPU": mpu}


def forecast(biz, cookies):
    """Full-month forecast — the Business Owner's Excel method (MPU_fc = MTD / pacing),
    fully dashboard-derived from the 'MTD' worksheet (overlays prev-month + current
    cumulative MPU by day):
       pacing  = prev_month_cum[day=days_elapsed] / prev_month_cum[full]
       MPU_fc  = MPU_MTD / pacing                       (stable; the AD6 = AC6/AF6)
       NPU_fc  = NPU_MTD / days_elapsed * total_days
       FPU_fc  = FPU_MTD / days_elapsed * total_days
    days_elapsed is taken from the current cumulative run's length (no date guessing)."""
    import calendar as _cal
    out = {}
    try:
        cols = _bootstrap_cols("RSTMonitoring", "MBSMonitoring", "MTD", cookies)
        ints = next((c["dataValues"] for c in cols if c.get("dataType") == "integer"), [])
        cum = [v for v in ints if v > 1000]              # drop the 1..31 day-number axis
        runs, cur = [], []                                # split into ascending runs
        for v in cum:
            if cur and v < cur[-1]:
                runs.append(cur); cur = [v]
            else:
                cur.append(v)
        if cur:
            runs.append(cur)
    except Exception as e:
        out["error"] = str(e)[:60]; return out
    if len(runs) < 2 or not runs[-2] or not runs[-1]:
        out["error"] = "MTD worksheet: could not split prev/current cumulative runs"
        return out
    prev, curr = runs[-2], runs[-1]
    days_elapsed = len(curr)
    y, mth = map(int, time.strftime("%Y-%m").split("-"))
    total_days = _cal.monthrange(y, mth)[1]
    mpu_mtd = curr[-1]
    npu, fpu = biz["NPU"]["value"], biz["FPU"]["value"]
    idx = min(days_elapsed - 1, len(prev) - 1)
    out.update(days_elapsed=days_elapsed, total_days=total_days,
               NPU_fc=npu / days_elapsed * total_days,
               FPU_fc=fpu / days_elapsed * total_days,
               Retain_MTD=biz["MPU"]["value"] - fpu,
               mpu_mtd=mpu_mtd, mpu_last_mtd=prev[idx], prev_full=prev[-1])
    pacing = prev[idx] / prev[-1] if prev[-1] else None
    out["pacing"] = pacing
    if pacing and 0 < pacing < 1:
        mpu_fc = mpu_mtd / pacing
        upper = mpu_mtd * total_days / days_elapsed     # linear is the absolute ceiling
        if mpu_mtd <= mpu_fc <= upper:
            out["MPU_fc"] = mpu_fc
            # confidence scales with elapsed coverage — early month is volatile
            # (VN payday spikes on 1st/15th + weekend ride patterns). Pacing already
            # bakes in last-month's day-shape, so mid/late-month is reliable.
            out["confidence"] = ("low — early month (<5 days)" if days_elapsed < 5 else
                                 "medium — first third of month" if days_elapsed < 10 else
                                 "high — pacing from prev-month cumulative")
        else:
            out["MPU_fc_suppressed"] = round(mpu_fc)
            out["note"] = "pacing out of plausible range"
    return out


def pull_merchant_mpu(cookies):
    """Current-month MPU per merchant from the 'YTM' worksheet (merchant-major,
    current month first, stride 13). Guarded: must be positive + descending."""
    cols = _bootstrap_cols("RSTMonitoring", "MBSMonitoring", "YTM", cookies)
    ints = next((c["dataValues"] for c in cols if c.get("dataType") == "integer"), [])
    if len(ints) < (len(MERCH_ORDER) - 1) * YTM_STRIDE + 1:
        raise RuntimeError("YTM worksheet: integer column too short")
    vals = [ints[k * YTM_STRIDE] for k in range(len(MERCH_ORDER))]
    if not (all(v > 0 for v in vals) and vals == sorted(vals, reverse=True)):
        raise RuntimeError(f"YTM merchant MPU guard failed (structure drift?): {vals}")
    return dict(zip(MERCH_ORDER, vals))


def pull_merchant_series(cookies):
    """Per-merchant MONTHLY MPU series from 'YTM' (the 13-value block per merchant
    we already fetch but discard all-but-first). Index 0 = current month, 1 = prev, …
    Returns {merchant: [m0, m1, …]} or {} if structure drifts (caller degrades)."""
    try:
        cols = _bootstrap_cols("RSTMonitoring", "MBSMonitoring", "YTM", cookies)
        ints = next((c["dataValues"] for c in cols if c.get("dataType") == "integer"), [])
        if len(ints) < (len(MERCH_ORDER) - 1) * YTM_STRIDE + YTM_STRIDE:
            return {}
        out = {}
        for k, name in enumerate(MERCH_ORDER):
            block = [v for v in ints[k * YTM_STRIDE:(k + 1) * YTM_STRIDE] if isinstance(v, (int, float))]
            # keep the leading run of positive months (drop trailing zeros/padding)
            series = []
            for v in block:
                if v <= 0:
                    break
                series.append(int(v))
            if series:
                out[name] = series
        return out
    except Exception as e:
        print("  merchant series skipped:", str(e)[:50], flush=True)
        return {}


def derive_signals(biz, merch, series=None, vol=None, fc=None):
    """Combine the dashboard pulls into NEW analytical signals — no fabrication, all
    computed from real numbers. Drives smarter CRM targeting (which merchant, which
    lever, how strong an offer). Every field degrades to None if its input is absent."""
    mpu = biz["MPU"]["value"]; npu = biz["NPU"]["value"]; fpu = biz["FPU"]["value"]
    rpu = mpu - fpu
    series = series or {}; vol = vol or {}; fc = fc or {}
    tgt = fc.get("_target"); fc_mpu = fc.get("MPU_fc")
    pace = (fc_mpu / mpu) if (fc_mpu and mpu) else None        # MBS month-end scale-up factor
    msum = sum(merch.values()) or 1
    gap = round(tgt - fc_mpu) if (tgt and fc_mpu and fc_mpu < tgt) else 0

    merchants = {}
    for name, cur in merch.items():
        # YTM block = [current-month MTD (PARTIAL), last full month, month before, …].
        # Index 0 is partial → NEVER compare it to a full month. Momentum/trend use the
        # FULL prior months only; the actionable signal is the full-month FORECAST vs last full month.
        s = series.get(name) or []
        full = [int(v) for v in s[1:] if isinstance(v, (int, float)) and v > 0]   # prior full months, recent-first
        last_full = full[0] if full else None
        fcast = round(cur * pace) if pace else None                               # this month projected to full
        momentum = ((full[0] - full[1]) / full[1]) if len(full) >= 2 and full[1] else None   # completed MoM
        proj_mom = ((fcast - last_full) / last_full) if (fcast and last_full) else None       # projected vs last full
        trend = None
        if len(full) >= 3 and full[1] and full[2]:
            trend = ("accelerating" if full[0] > full[1] > full[2]
                     else "decelerating" if full[0] < (full[1] + full[2]) / 2 else "steady")
        v = vol.get(name) or {}
        merchants[name] = {
            "mpu": cur, "share": cur / msum, "last_full": last_full,
            "momentum": momentum, "proj_mom": proj_mom, "trend": trend,
            "forecast": fcast, "cost_tpv": v.get("Cost/TPV"),
            "gap_alloc": round(gap * cur / msum) if gap else 0,
        }

    def _slipping(x):  # this month projected below last full month, or a falling full-month trend
        return x["trend"] == "decelerating" or (x["proj_mom"] is not None and x["proj_mom"] < -0.02)

    # funnel-leak: where is growth actually constrained?
    npu_pct_fpu = npu / fpu if fpu else None
    rpu_pct_mpu = rpu / mpu if mpu else None
    leak = ("acquisition" if (npu_pct_fpu is not None and npu_pct_fpu < 0.15)
            else "retention" if (rpu_pct_mpu is not None and rpu_pct_mpu > 0.9)
            else "balanced")
    rf = biz.get("Refund", {})
    refund_rate = (rf.get("value") / biz["Transactions"]["value"]
                   if rf.get("value") and biz.get("Transactions", {}).get("value") else None)
    return {
        "merchants": merchants,
        "funnel": {"npu_pct_fpu": npu_pct_fpu, "rpu_pct_mpu": rpu_pct_mpu, "leak": leak},
        "gap": gap, "refund_rate": refund_rate,
        # priority: biggest pools first, but a slipping merchant (projected below last
        # full month, or a falling full-month trend) is bumped up — that's where MPU is at risk
        "priority": [n for n, _ in sorted(
            merchants.items(),
            key=lambda kv: (kv[1]["share"] + (0.15 if _slipping(kv[1]) else 0)),
            reverse=True)],
    }


def get_window(workbook, view, cookies):
    cols = None
    ch = (f"workgroup_session_id={cookies['workgroup_session_id']}; "
          f"XSRF-TOKEN={cookies['XSRF-TOKEN']}; tableau_locale=en")
    embed = f"{ATLAS_BASE}/t/{SITE}/views/{workbook}/{view}?:embed=yes&:showVizHome=no"
    shell = urllib.request.urlopen(urllib.request.Request(embed, headers={"Cookie": ch}), timeout=30).read().decode()
    sid = re.search(r'"sessionid":"([^"]+)"', html.unescape(shell)).group(1)
    post = f"{ATLAS_BASE}/vizql/t/{SITE}/w/{workbook}/v/{view}/bootstrapSession/sessions/{sid}"
    raw = urllib.request.urlopen(urllib.request.Request(post, method="POST",
        data=urllib.parse.urlencode({"sheet_id": view}).encode(),
        headers={"Cookie": ch, "X-Tsi-Active-Tab": view,
                 "Content-Type": "application/x-www-form-urlencoded", "Accept": "text/javascript"}),
        timeout=300).read().decode("utf-8", errors="replace")
    ds = re.findall(r"\b(\d{1,2}/\d{1,2}/2026)\b", raw)
    return len(ds) and None  # window unreliable across charts; not used in report


def pull_merchant_volume(cookies):
    out = {}
    for label, (wb, view, sheets) in MERCH_VOL.items():
        d = {}
        for metric, sheet in sheets.items():
            try:
                d[metric], _ = bootstrap_tile(wb, view, sheet, cookies)
            except Exception as e:
                d[metric] = None
                print(f"  {label} {metric} FAIL {str(e)[:40]}", flush=True)
            time.sleep(0.3)
        if d.get("Discount") and d.get("TPV"):
            d["Cost/TPV"] = d["Discount"] / d["TPV"]
        print(f"  {label}: Trans {d.get('Transactions')} TPV {d.get('TPV')} Disc {d.get('Discount')}", flush=True)
        out[label] = d
    return out


# ------------------------------------------------------------ helpers
def _fmt(v):
    if not isinstance(v, (int, float)):
        return str(v)
    a = abs(v)
    if a >= 1e9: return f"{v/1e9:.2f}B"
    if a >= 1e6: return f"{v/1e6:.2f}M"
    if a >= 1e3: return f"{v/1e3:.1f}K"
    return f"{v:.2f}" if isinstance(v, float) else f"{v:,}"


def _pct(x):
    return f"{x*100:.1f}%"


def _ctpv(x):
    p = x * 100
    return f"{p:.3f}%" if p < 1 else f"{p:.1f}%"


def anomaly(change, good=True):
    if change is None:
        return None
    eff = change if good else -change
    if eff >= 0.05: return ("highlight", "📈 Highlight")
    if eff >= 0: return ("normal", "• Normal")
    if eff > -0.01: return ("watch", "👀 Watch")
    return ("alert", "🚨 Alert")


def _tag(change, good=True):
    a = anomaly(change, good)
    return f" [{a[1]}]" if a and a[0] != "normal" else ""


def _month_key():
    return time.strftime("%Y-%m")


# ------------------------------------------------------------ audit
def audit(biz, seg, merch):
    ok, msgs = True, []
    s = sum(seg[k] for k in ("NPU", "FPU", "Resurrected", "Retained"))
    # NOTE: this sum is tautological (FPU is the residual), so it's only a sanity
    # net. The REAL check below independently validates the Monthly extraction.
    if s != seg["MPU"]:
        ok = False; msgs.append(f"✗ MBS: segment sum {s:,} != MPU {seg['MPU']:,}")
    # REAL check: the Monthly-derived FPU residual must match the FPU tile minus NPU
    # (FPU tile = incl NPU). Catches drifted reals[1]/reals[19] offsets — which the
    # tautological sum cannot. If this fails, Retained/Resurrected are wrong -> abort.
    exp_fpu = biz["FPU"]["value"] - biz["NPU"]["value"]
    if abs(seg["FPU"] - exp_fpu) <= max(2, round(0.01 * abs(exp_fpu))):
        msgs.append(f"✓ MBS: Monthly split validated — FPU residual {seg['FPU']:,} ≈ tile−NPU {exp_fpu:,}")
    else:
        ok = False
        msgs.append(f"✗ MBS: FPU residual {seg['FPU']:,} != tile−NPU {exp_fpu:,} → Monthly offsets drifted")
    if seg["FPU"] <= 0:
        ok = False; msgs.append(f"✗ MBS: FPU residual non-positive ({seg['FPU']})")
    for label, v in merch.items():
        if not (0 < v < seg["MPU"]):
            ok = False; msgs.append(f"✗ {label}: MPU {v:,} out of range vs total {seg['MPU']:,}")
    if all(0 < v < seg["MPU"] for v in merch.values()):
        msgs.append(f"✓ merchants: each MPU within (0, total) — {', '.join(f'{k} {v:,}' for k,v in merch.items())}")
    return ok, msgs


# ------------------------------------------------------------ report
def _flag(change, good=True):
    a = anomaly(change, good)
    return {"highlight": "📈 Highlight", "normal": "✅ Normal",
            "watch": "👀 Watch", "alert": "🚨 Alert"}.get(a[0], "—") if a else "—"


def _risk_from_reach(reach):
    if reach is None:
        return "—"
    if reach >= 1.0:
        return "✅ On track"
    if reach >= 0.92:
        return "🟡 At risk"
    return "🔴 Needs action"


def _risk_word(reach):
    """Plain-text risk (no emoji) for monospace table alignment."""
    if reach is None:
        return "—"
    return "on track" if reach >= 1.0 else "at risk" if reach >= 0.92 else "needs action"


def _table(rows):
    """Monospace table (aligned columns) wrapped in <pre> for Telegram/Confluence."""
    w = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    out = []
    for r in rows:
        cells = [str(c).ljust(w[i]) if i == 0 else str(c).rjust(w[i]) for i, c in enumerate(r)]
        out.append("  ".join(cells).rstrip())
    return "<pre>" + "\n".join(out) + "</pre>"


def build_report(biz, seg, merch, fc=None, actions=None):
    """the Business Owner's STANDARD MONTHLY OUTPUT — 5 sections, MPU-focused, concise."""
    DIV = "━━━━━━━━━━━━━━━━━━━━"
    mpu = biz["MPU"]["value"]; npu = biz["NPU"]["value"]; fpu = biz["FPU"]["value"]
    rpu = mpu - fpu
    tgt = MPU_TARGET.get(_month_key())
    fc_mpu = fc.get("MPU_fc") if fc else None
    fc_reach = (fc_mpu / tgt) if (fc_mpu and tgt) else None
    last_mtd = fc.get("mpu_last_mtd") if fc else None
    y, m = map(int, time.strftime("%Y-%m").split("-"))
    prev_m = f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"
    cur_m = f"{y}-{m:02d}"
    L = []
    RULE = "─────────────────────"
    badge = ("🟢 ON TRACK" if (fc_reach or 0) >= 1 else
             "🟡 AT RISK" if (fc_reach or 0) >= 0.92 else
             "🔴 OFF TRACK") if fc_reach else "⚪ MTD"
    # ---- masthead ----
    L.append("<b>GROWTH ASSISTANT</b>  ·  MBS Mobility")
    L.append(f"<i>{time.strftime('%-d %b %Y')}  ·  daily MTD review</i>")
    L.append(RULE)
    # ---- executive summary (verdict first) ----
    L.append(f"<b>{badge}</b>")
    if fc_reach:
        L.append(f"MPU <b>{mpu:,}</b> → forecast <b>{_fmt(fc_mpu)}</b> · <b>{_pct(fc_reach)}</b> of {_fmt(tgt)} target")
        L.append("Gap is <b>acquisition</b> (NPU flat) — lever is re-engaging lapsed payers.")
    else:
        L.append(f"MPU <b>{mpu:,}</b> MTD")
    L.append(RULE)
    # ---- 1 · MTD snapshot ----
    L.append("📊 <b>MTD SNAPSHOT</b>   <i>MPU · now vs last MTD</i>")
    snap = [["", "now", "last MTD", "Δ", "f'cast"],
            ["MBS", f"{mpu:,}", f"{last_mtd:,}" if last_mtd else "—",
             (biz["MPU"].get("delta") or "—").replace("▲ ", "").replace("▼ ", ""),
             _fmt(fc_mpu) if fc_mpu else "—"]]
    for label, v in merch.items():
        snap.append([f"· {label}", f"{v:,}", "—", "—", "—"])
    L.append(_table(snap))
    L.append("")
    # ---- 2 · segment health ----
    L.append("🩺 <b>SEGMENT HEALTH</b>")
    health = [["segment", "Δ MTD", "vs target", "status"],
              ["MPU", (biz["MPU"].get("delta") or "—").replace("▲ ", "").replace("▼ ", ""),
               _pct(fc_reach) if fc_reach else "—", _risk_word(fc_reach)],
              ["FPU incl", (biz["FPU"].get("delta") or "—").replace("▲ ", "").replace("▼ ", ""),
               "—", "on track" if (biz["FPU"].get("change") or 0) >= 0.05 else "at risk"],
              ["NPU", (biz["NPU"].get("delta") or "—").replace("▲ ", "").replace("▼ ", ""),
               "—", "needs action"],
              ["RPU", "—", f"{_pct(rpu/mpu)} of MPU", "on track"]]
    L.append(_table(health))
    L.append("")
    # ---- 3 · top anomalies (What / Where / Why) ----
    L.append("🔎 <b>TOP ANOMALIES</b>")
    L.append(f"🔴 <b>NPU flat</b> — {npu:,} ({(biz['NPU'].get('delta') or '').strip()})")
    L.append(f"      └ NPU is only {_pct(npu/fpu)} of FPU {fpu:,} → first-payments are mostly existing users; net-new acquisition is the constraint.")
    if fc_reach and fc_reach < 1:
        gap = round(tgt - fc_mpu)
        L.append(f"🟡 <b>MPU pacing short</b> — f'cast {_fmt(fc_mpu)} = {_pct(fc_reach)} of target (~{gap:,} gap)")
        L.append(f"      └ With NPU flat, the gap rests on retention (RPU {_pct(rpu/mpu)} of MPU), which can't over-deliver.")
    rf = biz.get("Refund")
    if rf and (rf.get("change") or 0) >= 0.05:
        rr = rf["value"] / biz["Transactions"]["value"] if biz["Transactions"]["value"] else None
        L.append(f"🚨 <b>Refund rising</b> — {_fmt(rf['value'])} ({(rf.get('delta') or '').strip()})"
                 + (f", {_pct(rr)} of txns" if rr is not None else ""))
        L.append(f"      └ Refund {(rf.get('delta') or '').strip()} outpaces transactions {(biz['Transactions'].get('delta') or '').strip()} → refund rate climbing, not just volume.")
    L.append("")
    # ---- 4 · action plan (one card per lever / merchant) ----
    L.append("🎯 <b>ACTION PLAN</b>")
    for a in (actions or []):
        L.append(f"<b>{a['priority']} · {a['type']}" + (f" · {a['merchant']}" if a.get('merchant') else "") + "</b>")
        L.append(f"   • <b>Problem</b> — {a['problem']}")
        L.append(f"   • <b>Target</b> — {a['target']}")
        L.append(f"   • <b>Campaign</b> — {a['channel']} · {a['promo']}")
        L.append(f"   • <b>KPI</b> — {a['kpi']}")
        L.append("")
    # ---- 5 · CRM-ready ----
    L.append("📥 <b>CRM-READY</b>   <i>segments · draft</i>")
    for a in (actions or []):
        s = a["segment"]
        L.append(f"• <code>{s['name']}</code>")
        L.append(f"      {s['conditions']} · size {s['est_size']}")
    L.append(RULE)
    L.append("<i>Auto-generated by Growth Assistant — every number audited against the live dashboards.</i>")
    return "\n".join(L)


# ------------------------------------------------------------ delivery
def _tg_html(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"^[\-\*]\s+", "• ", text, flags=re.M)
    text = re.sub(r"&(?!(amp|lt|gt|quot|#\d+);)", "&amp;", text)
    return text


def _tg_send_one(text):
    payload = {"chat_id": int(TG_GROUP), "text": text, "parse_mode": "HTML"}
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=20)
        return True
    except urllib.error.HTTPError:
        payload.pop("parse_mode"); payload["text"] = re.sub(r"<[^>]+>", "", text)
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=20)
        return False


def _chunk(text, limit=3800):
    """Pack section-blocks (split on blank lines) into <=limit messages so a
    <pre> table is never split across two Telegram messages."""
    blocks = text.split("\n\n")
    out, cur = [], ""
    for b in blocks:
        if len(cur) + len(b) + 2 > limit and cur:
            out.append(cur); cur = b
        else:
            cur = (cur + "\n\n" + b) if cur else b
    if cur:
        out.append(cur)
    return out


def post_telegram(text):
    if not (TG_TOKEN and TG_GROUP):
        return "skipped (no token/group)"
    html_text = _tg_html(text)
    chunks = _chunk(html_text)
    all_html = all(_tg_send_one(c) for c in chunks)
    return f"posted to group ({len(chunks)} msg, {'HTML' if all_html else 'some plain'})"


def _esc(s):
    """Confluence-storage-safe text: drop non-BMP (emoji 400s), escape XML."""
    s = "".join(c for c in str(s) if ord(c) < 0x10000)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _report_to_storage(report):
    rep = "".join(c for c in report if ord(c) < 0x10000)
    rep = re.sub(r"&(?!(amp|lt|gt|quot|#\d+);)", "&amp;", rep)
    out = []
    for part in re.split(r"(<pre>.*?</pre>)", rep, flags=re.S):
        if part.startswith("<pre>"):
            out.append(part)
        else:
            out += [f"<p>{ln.strip()}</p>" for ln in part.split("\n") if ln.strip()]
    return "".join(out)


def _status(fc_reach):
    if fc_reach is None:
        return ("Grey", "N/A")
    if fc_reach >= 1.0:
        return ("Green", "ON TRACK")
    if fc_reach >= 0.92:
        return ("Yellow", "AT RISK")
    return ("Red", "OFF TRACK")


def _actions_storage(actions):
    """One panel per action: the recommendation + CRM segment spec + noti fields.
    Supports multiple actions/day (acquisition + per-merchant reactivation, …)."""
    if not actions:
        return ""
    blocks = ["<h3>Action plan &amp; noti suggestions (draft — Save, not Distribute)</h3>"]
    for a in actions:
        n = a.get("noti", {}); s = a.get("segment", {})
        va = n.get("variant_a", {}); vb = n.get("variant_b", {})
        head = f"{a['priority']} · {a['type']}" + (f" · {a['merchant']}" if a.get("merchant") else "")
        rows = [("Problem", a["problem"]), ("Cause (3W)", a["cause"]), ("Target", a["target"]),
                ("Campaign", f"{a['type']} · {a['channel']} · {a['promo']}"), ("KPI", a["kpi"]),
                ("Segment name", s.get("name", "")), ("Segment conditions", s.get("conditions", "")),
                ("Est. size", s.get("est_size", "")),
                (f"Noti A · {va.get('variant','')}", f"{va.get('title','')} — {va.get('body','')} (gửi {va.get('send','')})"),
                ("  A hypothesis", va.get("hyp", "")),
                (f"Noti B · {vb.get('variant','')}", f"{vb.get('title','')} — {vb.get('body','')} (gửi {vb.get('send','')})"),
                ("  B hypothesis", vb.get("hyp", "")),
                ("ZPA / ZPI", f"{n.get('zpa_redirection','')}  |  {n.get('zpi_redirection','')}")]
        trs = "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in rows)
        blocks.append(
            f"<ac:structured-macro ac:name=\"panel\"><ac:parameter ac:name=\"bgColor\">#FFFAE6</ac:parameter>"
            f"<ac:rich-text-body><p><strong>{_esc(head)}</strong></p>"
            f"<table><tbody>{trs}</tbody></table></ac:rich-text-body></ac:structured-macro>")
    return "".join(blocks)


def _t_head(*c): return "<tr>" + "".join(f"<th>{x}</th>" for x in c) + "</tr>"
def _t_row(*c): return "<tr>" + "".join(f"<td>{_esc(x)}</td>" for x in c) + "</tr>"
def _t(*rows): return "<table><tbody>" + "".join(rows) + "</tbody></table>"
def _lz(color, word): return (f"<ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"colour\">{color}"
                              f"</ac:parameter><ac:parameter ac:name=\"title\">{_esc(word)}</ac:parameter></ac:structured-macro>")


def build_confluence_day(biz, seg, merch, fc, actions):
    """Native Confluence storage for one day — real tables + panels (no <pre> dump,
    no duplicated action text). Telegram keeps its own monospace text version."""
    mpu = biz["MPU"]["value"]; npu = biz["NPU"]["value"]; fpu = biz["FPU"]["value"]; rpu = mpu - fpu
    tgt = MPU_TARGET.get(_month_key()); fc_mpu = fc.get("MPU_fc")
    fc_reach = (fc_mpu / tgt) if (fc_mpu and tgt) else None
    last_mtd = fc.get("mpu_last_mtd")
    dl = lambda k: (biz[k].get("delta") or "—").strip()
    H = []
    # 1. MTD snapshot — real table
    H.append("<h3>1. MTD snapshot · MPU</h3>")
    rows = [_t_head("", "now", "last", "Δ", "forecast"),
            _t_row("MBS", f"{mpu:,}", f"{last_mtd:,}" if last_mtd else "—", dl("MPU"), _fmt(fc_mpu) if fc_mpu else "—")]
    for k, v in merch.items():
        rows.append(_t_row(k, f"{v:,}", "—", "—", "—"))
    H.append(_t(*rows))
    H.append("<p><em>Merchant last-MTD / forecast not split on the dashboard.</em></p>")
    # 2. Segment health — real table with status lozenges
    cr, cw = _status(fc_reach)
    H.append("<h3>2. Segment health</h3>")
    H.append("<table><tbody>" + _t_head("segment", "Δ", "vs target", "risk")
             + f"<tr><td>MPU</td><td>{_esc(dl('MPU'))}</td><td>{_pct(fc_reach) if fc_reach else '—'}</td><td>{_lz(cr,cw)}</td></tr>"
             + f"<tr><td>FPU (incl NPU)</td><td>{_esc(dl('FPU'))}</td><td>—</td><td>{_lz('Green','ON TRACK') if (biz['FPU'].get('change') or 0)>=0.05 else _lz('Yellow','AT RISK')}</td></tr>"
             + f"<tr><td>NPU</td><td>{_esc(dl('NPU'))}</td><td>—</td><td>{_lz('Red','NEEDS ACTION')}</td></tr>"
             + f"<tr><td>RPU (returning)</td><td>—</td><td>{_pct(rpu/mpu)} of MPU</td><td>{_lz('Green','ON TRACK')}</td></tr>"
             + "</tbody></table>")
    # 3. Top anomalies — list (What/Where/Why)
    H.append("<h3>3. Top anomalies</h3><ul>")
    H.append(f"<li><strong>NPU flat</strong> — {npu:,} ({_esc(dl('NPU'))}). <em>Where</em>: MBS overall. "
             f"<em>Why</em>: NPU only {_pct(npu/fpu)} of FPU {fpu:,} → first-payments are mostly existing users; net-new acquisition is the constraint.</li>")
    if fc_reach and fc_reach < 1:
        H.append(f"<li><strong>MPU pacing short</strong> — forecast {_fmt(fc_mpu)} = {_pct(fc_reach)} of target (~{round(tgt-fc_mpu):,} gap). "
                 f"<em>Why</em>: with NPU flat, the gap rests on retention (RPU {_pct(rpu/mpu)} of MPU), which can't over-deliver.</li>")
    rfd = biz.get("Refund")
    if rfd and (rfd.get("change") or 0) >= 0.05:
        rr = rfd["value"] / biz["Transactions"]["value"]
        H.append(f"<li><strong>Refund rising</strong> — {_fmt(rfd['value'])} ({_esc(dl('Refund'))}), rate {_pct(rr)} of txns. "
                 f"<em>Why</em>: refund {_esc(dl('Refund'))} &gt; transactions {_esc(dl('Transactions'))} → refund rate climbing, not just volume.</li>")
    H.append("</ul>")
    # 4+5. Action plan + CRM segments + noti (panels — full, no duplication)
    H.append("<h3>4. Action plan · CRM segments · noti suggestions</h3>")
    H.append(_actions_storage(actions))
    # bottom line
    if fc_reach:
        verdict = ("on track" if fc_reach >= 1 else
                   f"slightly behind — forecast {_pct(fc_reach)} of target" if fc_reach >= 0.92 else
                   f"off track — forecast {_pct(fc_reach)} of target")
        H.append(f"<ac:structured-macro ac:name=\"panel\"><ac:parameter ac:name=\"bgColor\">"
                 f"{'#E3FCEF' if cr=='Green' else '#FFFAE6' if cr=='Yellow' else '#FFEBE6'}</ac:parameter>"
                 f"<ac:rich-text-body><p><strong>Bottom line:</strong> {_esc(verdict)}. "
                 f"Gap = acquisition (NPU flat); lever = re-engage lapsed payers.</p></ac:rich-text-body></ac:structured-macro>")
    return "".join(H)


def paste_confluence(report, mpu=None, fc_reach=None, actions=None, page_id=None, new_title=None,
                     day_storage=None):
    """Daily-log layout: header + latest panel + TOC + one collapsible <expand>
    per day (newest first, re-runs replace same day), each holding the analysis +
    noti suggestions. If the page has the Business Owner's spec, it's preserved at the bottom."""
    import base64, uuid
    page_id = page_id or OWNER_PAGE
    auth = open(os.path.expanduser("~/.config/confluence-token")).read().strip()
    h = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode(), "Content-Type": "application/json"}
    base = f"https://confluence.zalopay.vn/rest/api/content/{page_id}"
    d = json.load(urllib.request.urlopen(urllib.request.Request(base + "?expand=body.storage,version", headers=h), timeout=20))
    body = d["body"]["storage"]["value"]; ver = d["version"]["number"]
    date = time.strftime("%d/%m/%Y")
    color, word = _status(fc_reach)
    # ----- preserve the Business Owner's spec if this page has it; else build a clean daily page -----
    sm = re.search(r"<h[1-6][^>]*>(?:<span[^>]*>)?\s*AI Agent: Growth Assistant", body)
    spec = body[sm.start():] if sm else ""
    region = body[:sm.start()] if sm else body
    # ----- collect existing day blocks (split by each day-expand's start; nesting-safe) -----
    starts = [(m.start(), m.group(1)) for m in
              re.finditer(r'<ac:structured-macro ac:name="expand"[^>]*><ac:parameter ac:name="title">(\d{2}/\d{2}/\d{4})', region)]
    prior = []
    for i, (pos, dt) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(region)
        if dt != date:                       # drop today's old block (re-run replace)
            prior.append(region[pos:end])
    # ----- today's collapsible entry -----
    statlz = (f"<ac:structured-macro ac:name=\"status\"><ac:parameter ac:name=\"colour\">{color}</ac:parameter>"
              f"<ac:parameter ac:name=\"title\">{word}</ac:parameter></ac:structured-macro>")
    title = f"{date} · MPU {mpu:,} · forecast {_pct(fc_reach)}" if (mpu and fc_reach) else date
    day_body = f"<p>{statlz}</p>" + (day_storage or (_report_to_storage(report) + _actions_storage(actions)))
    today_block = (f"<ac:structured-macro ac:name=\"expand\" ac:macro-id=\"{uuid.uuid4()}\">"
                   f"<ac:parameter ac:name=\"title\">{_esc(title)}</ac:parameter>"
                   f"<ac:rich-text-body>{day_body}</ac:rich-text-body></ac:structured-macro>")
    # ----- header + latest panel + TOC (rebuilt each run) -----
    header = (
        "<h1>Growth Assistant — Daily Output</h1>"
        f"<ac:structured-macro ac:name=\"panel\"><ac:parameter ac:name=\"bgColor\">"
        f"{'#E3FCEF' if color=='Green' else '#FFFAE6' if color=='Yellow' else '#FFEBE6' if color=='Red' else '#F4F5F7'}"
        f"</ac:parameter><ac:rich-text-body><p><strong>Latest · {date}</strong> &nbsp; {statlz}"
        + (f" &nbsp; MPU <strong>{mpu:,}</strong> · forecast {_pct(fc_reach)} of target" if (mpu and fc_reach) else "")
        + "</p></ac:rich-text-body></ac:structured-macro>"
        "<ac:structured-macro ac:name=\"toc\"><ac:parameter ac:name=\"maxLevel\">2</ac:parameter></ac:structured-macro>"
        "<h2>Daily reports</h2>")
    new_body = header + today_block + "".join(prior) + spec
    payload = json.dumps({"type": "page", "title": new_title or d["title"],
        "version": {"number": ver + 1, "message": f"Growth report {date}"},
        "body": {"storage": {"value": new_body, "representation": "storage"}}}).encode()
    urllib.request.urlopen(urllib.request.Request(base + "?notifyWatchers=false", data=payload, method="PUT", headers=h), timeout=30)
    return ver + 1


def main():
    cookies = bs.extract_chrome_cookies(["atlas.vng.com.vn"])["atlas.vng.com.vn"]
    if "workgroup_session_id" not in cookies:
        raise SystemExit("Atlas session dead")
    print("pulling MBS business tiles...", flush=True)
    biz = pull_mbs_business(cookies)
    print("pulling segments + merchant MPU...", flush=True)
    seg = pull_segments(cookies, biz["MPU"]["value"], biz["NPU"]["value"])
    merch = pull_merchant_mpu(cookies)
    series = pull_merchant_series(cookies)          # per-merchant monthly history (for momentum)
    vol = pull_merchant_volume(cookies)             # per-merchant Trans/TPV/Discount (for efficiency)
    fc = forecast(biz, cookies)
    print(f"  segments {seg} | merchants {merch}", flush=True)
    print(f"  forecast={fc}", flush=True)
    print("\n----- AUDIT -----", flush=True)
    ok, msgs = audit(biz, seg, merch)
    for m in msgs:
        print("  " + m, flush=True)
    print(f"AUDIT {'PASSED' if ok else 'FAILED'}", flush=True)
    mpu = biz["MPU"]["value"]
    tgt = MPU_TARGET.get(_month_key())
    fc["_target"] = tgt
    fc_reach = (fc.get("MPU_fc") / tgt) if (fc.get("MPU_fc") and tgt) else None
    # multiple prioritized actions (acquisition + per-merchant reactivation), each w/ noti
    signals = derive_signals(biz, merch, series, vol, fc)
    print(f"  signals: leak={signals['funnel']['leak']} priority={signals['priority']}", flush=True)
    try:
        import crm_noti
        actions = crm_noti.build_actions(biz, seg, merch, fc, signals)
    except Exception as e:
        actions = []; print("  actions skipped:", str(e)[:60], flush=True)
    report = build_report(biz, seg, merch, fc, actions)
    print("\n===== REPORT =====\n" + report)
    print(f"\n  {len(actions)} actions: " + ", ".join(f"{a['priority']} {a['type']}{'/'+a.get('merchant','') if a.get('merchant') else ''}" for a in actions), flush=True)
    if not ok:
        print("\n[ABORT] audit failed — not sending.")
        return
    day_storage = build_confluence_day(biz, seg, merch, fc, actions)  # native Confluence (tables+panels)
    if "--confluence" in sys.argv or "--all" in sys.argv:
        print("\n[confluence·owner] v->", paste_confluence(report, mpu, fc_reach, actions, day_storage=day_storage))
        try:
            v = paste_confluence(report, mpu, fc_reach, actions, page_id="335581153",
                                 new_title="MBS Growth Assistant — Daily Output", day_storage=day_storage)
            print("[confluence·MVP] v->", v)
        except Exception as e:
            print("[confluence·MVP] FAIL:", str(e)[:80])
    if "--telegram" in sys.argv or "--all" in sys.argv:
        print("[telegram]", post_telegram(report))


if __name__ == "__main__":
    main()
