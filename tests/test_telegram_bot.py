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


def test_unknown_command():
    assert "Unknown" in t.handle_text("/nope")
