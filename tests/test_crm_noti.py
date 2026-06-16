"""Tests for the action engine + CRM noti generation (offline, pure functions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import crm_noti as c  # noqa: E402

BIZ = {"MPU": {"value": 548636, "delta": "▲ +3.4%", "change": 0.034},
       "NPU": {"value": 3026, "delta": "▼ -0.2%", "change": -0.002},
       "FPU": {"value": 25898, "delta": "▲ +5.4%", "change": 0.054},
       "Transactions": {"value": 3046001, "delta": "▲ +11.6%", "change": 0.116},
       "Refund": {"value": 328719, "delta": "▲ +18.0%", "change": 0.18}}
MERCH = {"Grab": 392315, "XANH SM": 156737, "Be": 84684, "AhaMove": 14480}
FC = {"_target": 801000, "MPU_fc": 761524, "prev_full": 736378, "mpu_last_mtd": 530520}


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
    series = {"Grab": [392315, 529335, 516449, 496331], "XANH SM": [156737, 221129, 186131],
              "Be": [84684, 135394, 136706, 138857], "AhaMove": [14480, 25168]}
    sig = m.derive_signals(BIZ, MERCH, series, {}, FC)
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


def test_fmtk():
    assert c._fmtk(129300) == "129K"
    assert c._fmtk(950) == "950"
