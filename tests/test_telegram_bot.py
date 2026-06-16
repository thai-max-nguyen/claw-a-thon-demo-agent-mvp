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


def test_confirm_lists_real_draft_ids():
    t.PENDING["actions"] = [
        {"merchant": "Grab", "noti_name": "[MBS] Grab Noti_RPU_Grab_Churn", "segment": {"name": "g"}},
        {"type": "Acquisition", "noti_name": "[MBS] Mobility Noti_NPU_MBS_Acq", "segment": {"name": "a"}},
        {"merchant": "XANH SM", "noti_name": "[MBS] XANH SM ...", "segment": {"name": "x"}},
        {"merchant": "Be", "noti_name": "[MBS] Be ...", "segment": {"name": "b"}},
    ]
    out = t.handle_text("/confirm")
    for nid in ("16550", "16559", "16560", "16561"):
        assert nid in out
    assert "DRAFT" in out and "INACTIVE" in out
    assert "office.zalopay.vn" in out          # review link present


def test_unknown_command():
    assert "Unknown" in t.handle_text("/nope")
