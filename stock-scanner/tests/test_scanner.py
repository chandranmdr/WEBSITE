import json

import pandas as pd
import pytest

from run_scanner import main
from screener.intraday import expected_volume_fraction
from screener.scanner import ScanParams, evaluate, new_alerts

ITEM = {"symbol": "XYZ", "avg_vol50": 390_000, "atr14": 2.0}
SETUP = {"setup": "breakout_20d", "trigger": 100.0, "stop": 98.0}
P = ScanParams(near_pct=0.5, max_gap_pct=1.0, target_r=2.0, min_rvol=1.0)


def session(path, volume=1000):
    """1-minute bars where each bar's open/high/low/close all come from `path` (list of (low, high, close))."""
    idx = pd.date_range("2026-10-13 09:30", periods=len(path), freq="1min", tz="America/New_York")
    opens = [path[0][2]] + [c for _, _, c in path[:-1]]
    return pd.DataFrame({"open": opens, "high": [h for _, h, _ in path], "low": [l for l, _, _ in path],
                         "close": [c for _, _, c in path], "volume": volume}, index=idx)


def test_waiting_then_near():
    assert evaluate(ITEM, SETUP, session([(98.5, 99, 98.8)]), P).status == "waiting"
    st = evaluate(ITEM, SETUP, session([(98.5, 99, 98.8), (99.5, 99.8, 99.7)]), P)
    assert st.status == "near" and st.dist_pct == pytest.approx(-0.3)


def test_trigger_then_target():
    bars = session([(99, 99.5, 99.4), (99.4, 100.2, 100.1), (100, 103, 102.9), (103, 104.5, 104.2)])
    st = evaluate(ITEM, SETUP, bars, P)
    assert st.entry == 100 and st.target == 104
    assert st.status == "target" and st.time == "09:33"


def test_trigger_then_stop():
    st = evaluate(ITEM, SETUP, session([(99, 100.5, 99.6), (97.5, 100, 97.8)]), P)
    assert st.status == "stopped" and st.entry == 100


def test_stop_before_trigger_invalidates():
    st = evaluate(ITEM, SETUP, session([(97.9, 99, 98.5), (98.5, 100.5, 100.3)]), P)
    assert st.status == "invalidated"


def test_gap_handling():
    big_gap = session([(102, 103, 102.5)])
    big_gap.iloc[0, 0] = 102.0
    assert evaluate(ITEM, SETUP, big_gap, P).status == "gapped"
    small_gap = session([(100.4, 101, 100.8)])
    small_gap.iloc[0, 0] = 100.5
    st = evaluate(ITEM, SETUP, small_gap, P)
    assert st.status == "triggered" and st.entry == 100.5  # filled at the open, not the trigger


def test_rvol_is_time_of_day_adjusted():
    # Exactly the expected volume for the first 2 minutes -> RVOL 1.0
    expected = ITEM["avg_vol50"] * expected_volume_fraction(2)
    st = evaluate(ITEM, SETUP, session([(99, 99.5, 99.4), (99.4, 100.2, 100.1)], volume=expected / 2), P)
    assert st.rvol == pytest.approx(1.0, abs=0.01)
    assert expected_volume_fraction(30) > 30 / 390  # the open is busier than average


def test_alerts_only_move_forward():
    seen = {}
    waiting = evaluate(ITEM, SETUP, session([(98.5, 99, 98.8)]), P)
    trig = evaluate(ITEM, SETUP, session([(99, 100.5, 100.2)]), P)
    assert new_alerts([waiting], seen) == []
    assert [a.status for a in new_alerts([trig], seen)] == ["triggered"]
    assert new_alerts([trig], seen) == []  # no repeat


def test_demo_session_end_to_end(tmp_path):
    from run_screener import main as screen
    assert screen(["--demo", "--out", str(tmp_path)]) == 0
    wl = tmp_path / "latest" / "watchlist.json"
    assert main(["--demo", "--watchlist", str(wl), "--out", str(tmp_path / "scan"), "--alerts", "logfile"]) == 0
    log = (tmp_path / "scan" / "alerts.log").read_text()
    assert "TRIGGERED" in log
    assert (tmp_path / "scan" / "scanner.html").exists()
    # --once over the same simulated day must not crash and must dedupe against the lookback window
    assert main(["--demo", "--once", "--watchlist", str(wl), "--out", str(tmp_path / "once"), "--alerts", "logfile"]) == 0
