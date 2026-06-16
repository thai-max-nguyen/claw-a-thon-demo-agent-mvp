"""Offline routing tests for the Telegram bridge (no network)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telegram_bot as t  # noqa: E402


def test_help_is_mbs():
    assert "MBS Growth Assistant" in t.handle_text("/help")


def test_noncommand_ignored():
    assert t.handle_text("just chatting") == ""


def test_confirm_requires_run_first():
    t.PENDING.clear()
    out = t.handle_text("/confirm")
    assert "/run" in out and "Nothing to confirm" in out


def test_confirm_reports_embedded_content(monkeypatch):
    # /confirm calls the full-auto CRM client; mock it to test the reply formatting offline.
    import crm_client
    monkeypatch.setattr(crm_client, "stage_drafts", lambda actions: [
        {"id": 16550, "name": "[MBS] Grab ...", "title": "Đặt xe tháng này",
         "body": "Thanh toán Grab...", "zpa": "zalopay://launch/app/2222", "zpi": "https://grb.to/Homepage"},
    ])
    t.PENDING["actions"] = [{"merchant": "Grab", "noti_name": "[MBS] Grab", "segment": {"name": "g"}}]
    out = t.handle_text("/confirm")
    assert "16550" in out and "DRAFT" in out
    assert "Title" in out and "Body" in out and "ZPA" in out      # embedded content shown
    assert "office.zalopay.vn" in out                              # review link


def test_confirm_handles_dead_session(monkeypatch):
    import crm_client
    def boom(actions):
        raise crm_client.CrmSessionError("CRM session expired — refocus the CRM tab")
    monkeypatch.setattr(crm_client, "stage_drafts", boom)
    t.PENDING["actions"] = [{"merchant": "Grab", "segment": {"name": "g"}}]
    out = t.handle_text("/confirm")
    assert "⚠️" in out and "session" in out.lower()


def test_adjust_requires_run_first():
    t.PENDING.clear()
    out = t.handle_text("/adjust Grab 30K")
    assert "/run" in out and "Nothing to adjust" in out


def test_adjust_revises_pending_and_confirm_uses_latest():
    # seed a real proposal, adjust it, and verify PENDING now holds the revised plan
    import crm_noti as c
    BIZ = {"MPU": {"value": 500000, "delta": "▲ +3.0%", "change": 0.03},
           "NPU": {"value": 3000, "delta": "▼ -0.3%", "change": -0.003},
           "FPU": {"value": 30000, "delta": "▲ +5.0%", "change": 0.05},
           "Transactions": {"value": 3000000}, "Refund": {"value": 300000}}
    MERCH = {"Grab": 300000, "XANH SM": 120000, "Be": 60000, "AhaMove": 20000}
    FC = {"_target": 735000, "MPU_fc": 700000, "prev_full": 680000}
    t.PENDING["actions"] = c.build_actions(BIZ, {}, MERCH, FC)
    out = t.handle_text("/adjust Grab 30K, drop Be")
    assert "Adjusted" in out and "30K" in out
    # PENDING (what /confirm will stage) reflects the latest revision
    assert all(a.get("merchant") != "Be" for a in t.PENDING["actions"])
    assert "30K" in next(a for a in t.PENDING["actions"] if a.get("merchant") == "Grab")["promo"]
    t.PENDING.clear()


def test_help_lists_adjust():
    assert "/adjust" in t.handle_text("/help")


def test_unknown_command():
    assert "Unknown" in t.handle_text("/nope")
