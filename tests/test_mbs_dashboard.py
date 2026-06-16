"""Offline tests for the dashboard-only MBS growth pipeline (pure functions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mbs_growth as m  # noqa: E402


def test_anomaly_tiers():
    assert m.anomaly(0.129, True)[0] == "highlight"      # >= +5%
    assert m.anomaly(0.02, True)[0] == "normal"          # 0..+5%
    assert m.anomaly(-0.005, True)[0] == "watch"         # -1..0
    assert m.anomaly(-0.03, True)[0] == "alert"          # <= -1%
    # cost metric polarity flips: a rise is bad
    assert m.anomaly(0.219, False)[0] == "alert"         # refund +21.9% -> alert
    assert m.anomaly(None, True) is None


def test_tag_hides_normal():
    assert m._tag(0.02, True) == ""                       # normal -> no tag
    assert "Highlight" in m._tag(0.13, True)
    assert "Alert" in m._tag(0.22, False)


def test_fmt():
    assert m._fmt(2834570) == "2.83M"
    assert m._fmt(227881000640) == "227.88B"
    assert m._fmt(2828) == "2.8K"
    assert m._fmt(531905) == "531.9K"


def test_ctpv_precision():
    assert m._ctpv(0.000296) == "0.030%"                  # small -> 3dp
    assert m._ctpv(0.0912) == "9.1%"                      # large -> 1dp


def test_delta_pct():
    assert abs(m._delta_pct("▲ +12.9%") - 0.129) < 1e-9
    assert abs(m._delta_pct("▼ -3%") + 0.03) < 1e-9
    assert m._delta_pct(None) is None
    assert m._delta_pct("  ") is None


def test_audit_segment_sum_reconciles():
    biz = {"MPU": {"value": 531905}, "NPU": {"value": 2828}, "FPU": {"value": 24027}}
    seg = {"MPU": 531905, "NPU": 2828, "FPU": 21199, "Resurrected": 94440, "Retained": 413438}
    merch = {"Grab": 379892, "XANH SM": 150542, "Be": 81194, "AhaMove": 13856}
    ok, msgs = m.audit(biz, seg, merch)
    assert ok is True
    assert any("Monthly split validated" in x for x in msgs)   # the REAL (non-tautological) check


def test_audit_catches_drifted_monthly_offsets():
    # Monthly extraction drifted: Retained/Resurrected wrong, but FPU residual still
    # makes the sum == MPU (tautology). The real check (FPU residual vs tile-NPU) must catch it.
    biz = {"MPU": {"value": 531905}, "NPU": {"value": 2828}, "FPU": {"value": 24027}}
    seg = {"MPU": 531905, "NPU": 2828, "FPU": 50000, "Resurrected": 60000, "Retained": 419077}
    assert sum(seg[k] for k in ("NPU", "FPU", "Resurrected", "Retained")) == seg["MPU"]  # tautology holds
    ok, _ = m.audit(biz, seg, {"Grab": 379892})
    assert ok is False                                    # real check (50000 != 24027-2828) catches it


def test_audit_catches_merchant_over_total():
    biz = {"MPU": {"value": 531905}, "NPU": {"value": 2828}, "FPU": {"value": 24027}}
    seg = {"MPU": 531905, "NPU": 2828, "FPU": 21199, "Resurrected": 94440, "Retained": 413438}
    merch = {"Grab": 999999999}                            # > total -> invalid
    ok, _ = m.audit(biz, seg, merch)
    assert ok is False


def test_status_tiers():
    assert m._status(1.0) == ("Green", "ON TRACK")
    assert m._status(0.95) == ("Yellow", "AT RISK")
    assert m._status(0.80) == ("Red", "OFF TRACK")
    assert m._status(None) == ("Grey", "N/A")


def test_esc_strips_emoji_and_escapes():
    out = m._esc("Đặt xe 🚕 <b> & 'x'")
    assert "🚕" not in out                                  # non-BMP dropped (Confluence 400)
    assert "&lt;b&gt;" in out and "&amp;" in out
    assert "Đặt xe" in out                                  # BMP Vietnamese kept


def test_build_confluence_day_native_no_dup():
    import crm_noti as c
    biz = {"MPU": {"value": 548636, "delta": "▲ +3.4%", "change": 0.034},
           "NPU": {"value": 3026, "delta": "▼ -0.2%", "change": -0.002},
           "FPU": {"value": 25898, "delta": "▲ +5.4%", "change": 0.054},
           "Transactions": {"value": 3046001, "delta": "▲ +11.6%", "change": 0.116},
           "Refund": {"value": 328719, "delta": "▲ +18.0%", "change": 0.18}}
    merch = {"Grab": 392315, "XANH SM": 156737, "Be": 84684, "AhaMove": 14480}
    fc = {"_target": 801000, "MPU_fc": 761524, "prev_full": 736378, "mpu_last_mtd": 530520}
    actions = c.build_actions(biz, {}, merch, fc)
    s = m.build_confluence_day(biz, {}, merch, fc, actions)
    assert "<table>" in s                                   # real tables, not <pre>
    assert "<pre>" not in s
    assert 'ac:name="status"' in s and 'ac:name="panel"' in s
    assert s.count("Problem") == len(actions)               # no duplication (1 per action panel)
    assert "548,636" in s and "392,315" in s and "530,520" in s
    assert "Bottom line" in s


def test_chunk_keeps_pre_intact():
    pre = "<pre>line1\nline2\nline3</pre>"
    text = "A\n\n" + pre + "\n\nB"
    chunks = m._chunk(text, limit=10_000)
    assert any(pre in c for c in chunks)                  # <pre> never split
    # tiny limit still never splits a single block mid-way
    chunks2 = m._chunk(text, limit=5)
    assert all(pre in c for c in chunks2 if "<pre>" in c)


def test_derive_signals_momentum_leak_forecast():
    biz = {"MPU": {"value": 548636}, "NPU": {"value": 3026}, "FPU": {"value": 25898},
           "Transactions": {"value": 3046001}, "Refund": {"value": 328719}}
    merch = {"Grab": 392315, "XANH SM": 156737, "Be": 84684, "AhaMove": 14480}
    series = {"Grab": [392315, 410000, 420000], "XANH SM": [156737, 150000, 148000],
              "Be": [84684, 84000, 83000], "AhaMove": [14480, 14000]}
    vol = {"Grab": {"Cost/TPV": 0.07}}
    fc = {"_target": 801000, "MPU_fc": 761524}
    s = m.derive_signals(biz, merch, series, vol, fc)
    g = s["merchants"]["Grab"]
    assert g["momentum"] < 0 and g["trend"] == "decelerating"   # 392k after 410k,420k
    assert g["forecast"] > g["mpu"]                              # pace > 1 applied per merchant
    assert g["cost_tpv"] == 0.07
    assert s["funnel"]["leak"] == "acquisition"                 # NPU 11.7% of FPU < 15%
    assert s["gap"] > 0 and sum(x["gap_alloc"] for x in s["merchants"].values()) > 0
    assert s["priority"][0] in ("Grab", "XANH SM")              # biggest pools lead


def test_derive_signals_degrades_without_history():
    biz = {"MPU": {"value": 500000}, "NPU": {"value": 3000}, "FPU": {"value": 25000},
           "Transactions": {"value": 3000000}, "Refund": {"value": 300000}}
    s = m.derive_signals(biz, {"Grab": 300000, "Be": 100000}, None, None, {"_target": 600000, "MPU_fc": 550000})
    assert s["merchants"]["Grab"]["momentum"] is None           # no series -> graceful
    assert s["funnel"]["leak"] in ("acquisition", "retention", "balanced")


def test_kpi_target_present():
    assert m.MPU_TARGET["2026-06"] == 801000


def test_tg_html_safe():
    out = m._tg_html("**bold** & <b>keep</b>")
    assert "<b>bold</b>" in out
    assert "&amp;" in out                                  # bare & escaped
