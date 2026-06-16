"""Tests for the action engine + CRM noti generation (offline, pure functions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_noti as c  # noqa: E402

# Fixtures are FAKE round numbers (no real business data) — shaped to exercise the logic:
# NPU/FPU = 10% (< 15% → acquisition leak), MPU_fc < target (gap > 0), Grab-dominant merchants.
BIZ = {"MPU": {"value": 500000, "delta": "▲ +3.0%", "change": 0.03},
       "NPU": {"value": 3000, "delta": "▼ -0.3%", "change": -0.003},
       "FPU": {"value": 30000, "delta": "▲ +5.0%", "change": 0.05},
       "Transactions": {"value": 3000000, "delta": "▲ +10.0%", "change": 0.10},
       "Refund": {"value": 300000, "delta": "▲ +15.0%", "change": 0.15}}
MERCH = {"Grab": 300000, "XANH SM": 120000, "Be": 60000, "AhaMove": 20000}
FC = {"_target": 735000, "MPU_fc": 700000, "prev_full": 680000, "mpu_last_mtd": 460000}  # gap 35K, pace 1.4
# YTM blocks: index0 = PARTIAL current MTD, then full prior months (pace ≈ 1.4 → full ≈ 1.4×partial)
SERIES = {"Grab": [300000, 420000, 410000, 400000], "XANH SM": [120000, 168000, 160000, 155000],
          "Be": [60000, 82000, 84000, 86000], "AhaMove": [20000, 28000, 27000, 26000]}


def test_actions_count_and_merchants():
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    assert len(acts) == 4                                  # P1 + 3 merchant P2 (AhaMove excluded)
    assert acts[0]["type"] == "Acquisition" and acts[0]["priority"] == "P1"
    merchants = [a.get("merchant") for a in acts if a.get("merchant")]
    assert merchants == ["Grab", "XANH SM", "Be"]         # biggest pool first
    assert "AhaMove" not in merchants


def test_segment_naming_format():
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    names = [a["segment"]["name"] for a in acts]
    assert names[0] == "Noti_NPU_MBS_Acq_" + __import__("time").strftime("%d/%m")
    assert any(n.startswith("Noti_RPU_Grab_Churn_") for n in names)
    assert any(n.startswith("Noti_RPU_XANHSM_Churn_") for n in names)  # space stripped


def test_appid_in_conditions():
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    grab = next(a for a in acts if a.get("merchant") == "Grab")
    assert "App ID 222" in grab["segment"]["conditions"]
    assert "2026-05" not in grab["segment"]["conditions"] or "Inclusion" in grab["segment"]["conditions"]


def test_noti_merchant_filled_and_deeplinks():
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    grab = next(a for a in acts if a.get("merchant") == "Grab")["noti"]
    assert "{merchant}" not in grab["variant_a"]["body"]   # filled
    assert "Grab" in grab["variant_a"]["body"]
    assert grab["zpa_redirection"] == "zalopay://launch/app/2222"
    assert grab["zpi_redirection"] == "https://grb.to/Homepage"
    be = next(a for a in acts if a.get("merchant") == "Be")["noti"]
    assert be["zpa_redirection"] == "zalopay://launch/app/1341"


def test_first_name_param_preserved():
    n = c.build_noti_content({"type": "Reactivation", "merchant": "Grab"})
    assert "{first_name}" in n["variant_a"]["title"]        # dynamic param kept for CRM


def test_scenario_mapping():
    assert c.build_noti_content({"type": "Acquisition"})["campaign"].startswith("FPU")
    assert c.build_noti_content({"type": "Reactivation", "merchant": "Be"})["campaign"].startswith("RPU")
    assert c.build_noti_content({"type": "Resurrection", "merchant": "Be"})["campaign"].startswith("RSPU")


def test_brand_is_zalopay_not_camelcase():
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    blob = str(acts)
    assert "ZaloPay" not in blob                            # brand must be 'Zalopay'
    assert "Zalopay" in blob


def test_no_crash_when_forecast_suppressed():
    fc = {"_target": 801000, "prev_full": 736378}           # no MPU_fc -> gap None
    acts = c.build_actions(BIZ, {}, MERCH, fc)
    assert len(acts) == 4                                   # must not raise on None gap
    assert "vs target" in acts[0]["cause"]


def test_acquisition_deeplink_is_per_merchant_note():
    n = c.build_noti_content({"type": "Acquisition"})        # no merchant
    assert "see deeplink table" in n["zpa_redirection"]


def test_no_placeholder_leaks_in_any_action():
    # every action's noti copy must be fully rendered — no literal {merchant} shipped,
    # including the cross-merchant Acquisition action (which has no merchant).
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    for a in acts:
        for var in ("variant_a", "variant_b"):
            for fld in ("title", "body"):
                assert "{merchant}" not in a["noti"][var][fld], f"{a.get('type')}/{var}/{fld} leaked {{merchant}}"


def test_acquisition_noti_has_no_merchant_placeholder():
    n = c.build_noti_content({"type": "Acquisition"})       # no merchant
    assert "{merchant}" not in n["variant_a"]["body"]
    assert "{merchant}" not in n["variant_b"]["body"]


def test_noti_label_rule():
    # rule: "[MBS] <Merchant> <segment name>"; cross-merchant Acquisition -> "Mobility"
    acts = c.build_actions(BIZ, {}, MERCH, FC)
    by = {a.get("merchant"): a for a in acts}
    assert by["Grab"]["noti_name"] == "[MBS] Grab " + by["Grab"]["segment"]["name"]
    assert by["XANH SM"]["noti_name"] == "[MBS] XANH SM " + by["XANH SM"]["segment"]["name"]
    acq = next(a for a in acts if a["type"] == "Acquisition")
    assert acq["noti_name"].startswith("[MBS] Mobility ")
    assert all(a["noti_name"].startswith("[MBS] ") for a in acts)


def test_build_actions_uses_signals():
    import mbs_growth as m
    sig = m.derive_signals(BIZ, MERCH, SERIES, {}, FC)
    acts = c.build_actions(BIZ, {}, MERCH, FC, sig)
    grab = next(a for a in acts if a.get("merchant") == "Grab")
    assert "projected" in grab["problem"] and "last full month" in grab["problem"]   # projection surfaced
    assert "đến 50K" in grab["promo"] or "đến 30K" in grab["promo"]   # offer tiered by gap
    # still produces the full set + no placeholder leak
    assert len(acts) == 4
    for a in acts:
        assert "{merchant}" not in a["noti"]["variant_a"]["body"]


def test_build_actions_no_signals_still_works():
    acts = c.build_actions(BIZ, {}, MERCH, FC)            # signals omitted -> backward compatible
    assert len(acts) == 4 and acts[0]["type"] == "Acquisition"


# ---- content & segment MATCH the purpose (semantic correctness, not just shape) ----
def test_acquisition_segment_targets_nonpayers():
    acq = next(a for a in c.build_actions(BIZ, {}, MERCH, FC) if a["type"] == "Acquisition")
    cond = acq["segment"]["conditions"].lower()
    assert "opened mobility" in cond and "exclusion" in cond and "payment" in cond   # target = non-payers
    assert acq["noti"]["campaign"].startswith("FPU")                                 # first-payment scenario
    blob = (acq["noti"]["variant_a"]["title"] + acq["noti"]["variant_a"]["body"] +
            acq["noti"]["variant_b"]["title"] + acq["noti"]["variant_b"]["body"]).lower()
    assert "đầu tiên" in blob or "lần đầu" in blob                                    # copy = first-ride themed


def test_reactivation_segment_deeplink_copy_match_merchant():
    deep = {"Grab": "app/2222", "XANH SM": "app/1653", "Be": "app/1341"}
    for a in c.build_actions(BIZ, {}, MERCH, FC):
        mer = a.get("merchant")
        if not mer:
            continue
        cond = a["segment"]["conditions"]
        assert f"txn at {mer} in" in cond and "Exclusion" in cond          # lapsed = paid prev, not this month
        assert deep[mer] in a["noti"]["zpa_redirection"]                   # deeplink matches the merchant
        body = a["noti"]["variant_a"]["body"] + a["noti"]["variant_b"]["body"]
        assert mer in body                                                 # copy names the merchant
        assert a["segment"]["name"].startswith(f"Noti_RPU_{mer.replace(' ', '')}_Churn")


def test_offer_tiers_to_gap():
    import mbs_growth as m
    sig = m.derive_signals(BIZ, MERCH, SERIES, {}, FC)
    by = {a.get("merchant"): a for a in c.build_actions(BIZ, {}, MERCH, FC, sig)}
    tier = lambda p: 50 if "50K" in p else 30
    assert tier(by["Grab"]["promo"]) > tier(by["Be"]["promo"])             # bigger gap → stronger offer


def test_fmtk():
    assert c._fmtk(129300) == "129K"
    assert c._fmtk(950) == "950"
