"""MBS pipeline tests — KPI math + report shape. No network (uses sample data)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mbs_report as m  # noqa: E402
import telegram_bot as tg  # noqa: E402


def test_compute_kpis():
    k = m.compute(m.load_rows())
    cur = k["cur"]
    # sample 2026-06-15 totals: 182340+95120+64210+210880+30410 = 582960
    assert cur["tx"] == 582960
    assert cur["rev"] == 4521000000 + 1820000000 + 980000000 + 3110000000 + 2740000000
    assert 0.95 <= cur["sr"] <= 1.0
    assert k["prev"] == "2026-06-14"


def test_top_movers_sorted():
    k = m.compute(m.load_rows())
    deltas = [abs(d) for _, _, d in k["movers"]]
    assert deltas == sorted(deltas, reverse=True)  # sorted by magnitude desc
    assert len(k["movers"]) == 5


def test_report_text_shape():
    k = m.compute(m.load_rows())
    txt = m.report_text(k)
    assert "MBS Daily Report" in txt
    assert "Transactions: 582,960" in txt
    assert "Success rate:" in txt


def test_telegram_report_and_action_routing():
    # /report routes to the MBS pipeline (stub narrative is fine offline)
    rep = tg.handle_text("/report")
    assert "MBS Daily Report" in rep
    # /action acknowledges + queues
    assert "Action received" in tg.handle_text("/action push alert if withdrawal drops >5%")
    assert tg.handle_text("/action").startswith("Usage:")
