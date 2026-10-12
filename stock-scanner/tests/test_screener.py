import json

import numpy as np
import pandas as pd
import pytest

from run_screener import main
from screener.indicators import add_indicators, atr, rsi, sma, snapshot
from screener.rules import Config, Setup, load_config, run_setups


def bars(close, spread=1.0, volume=1_000_000):
    close = pd.Series(close, dtype=float, index=pd.bdate_range("2024-01-01", periods=len(close)))
    return pd.DataFrame({"open": close, "high": close + spread, "low": close - spread, "close": close, "volume": volume})


def test_sma_and_rsi_edges():
    s = pd.Series(range(1, 31), dtype=float)
    assert sma(s, 5).iloc[-1] == 28
    assert rsi(s, 14).iloc[-1] == 100            # only gains
    assert rsi(-s, 14).iloc[-1] == pytest.approx(0)  # only losses
    assert rsi(s, 14).iloc[:14].isna().all()


def test_atr_constant_range():
    df = bars(np.full(40, 100.0), spread=2.0)
    assert atr(df, 14).iloc[-1] == pytest.approx(4.0)


def test_breakout_columns_exclude_today():
    close = np.r_[np.full(30, 100.0), 110.0]
    d = add_indicators(bars(close, volume=np.r_[np.full(30, 1e6), 3e6])).iloc[-1]
    assert d["high20"] == 101 and d["close"] > d["high20"]
    assert d["rvol"] == pytest.approx(3.0)


def test_snapshot_ranks_relative_strength():
    up = bars(np.linspace(50, 150, 300))
    down = bars(np.linspace(150, 50, 300))
    snap = snapshot({"UP": up, "DOWN": down}).set_index("symbol")
    assert snap.loc["UP", "rs_rank"] > snap.loc["DOWN", "rs_rank"]
    assert snap.loc["UP", "close"] > snap.loc["UP", "sma200"]


def test_run_setups_levels_and_limit():
    snap = pd.DataFrame({
        "symbol": ["A", "B", "C"], "close": [100.0, 50, 5], "high": [102.0, 51, 6], "low": [98.0, 49, 4],
        "dollar_vol20": [1e9, 1e9, 1e9], "rs_rank": [90, 80, 99],
    })
    cfg = Config(universe=[], base_filter="close >= 10",
                 setups=[Setup(name="strong", description="", condition="rs_rank >= 50", trigger="high", stop="low", limit=1)])
    hits = run_setups(snap, cfg)
    assert hits["symbol"].tolist() == ["A"]  # C fails base filter, limit keeps the top-ranked
    assert hits.iloc[0][["trigger", "stop"]].tolist() == [102, 98]
    assert hits.iloc[0]["risk_pct"] == pytest.approx(3.92)


def test_bad_condition_names_setup():
    cfg = Config(universe=[], base_filter="", setups=[Setup(name="oops", description="", condition="nope > 1")])
    with pytest.raises(ValueError, match="oops"):
        run_setups(pd.DataFrame({"symbol": ["A"], "close": [1.0]}), cfg)


def test_shipped_config_loads():
    cfg = load_config("config.yaml")
    assert {"sp500", "nasdaq100"} == set(cfg.universe)
    assert len(cfg.setups) >= 4


def test_demo_end_to_end(tmp_path):
    assert main(["--demo", "--out", str(tmp_path)]) == 0
    wl = json.loads((tmp_path / "latest" / "watchlist.json").read_text())
    assert wl["count"] == len(wl["symbols"]) > 0
    first = wl["symbols"][0]["setups"][0]
    assert first["trigger"] > first["stop"]
    assert (tmp_path / "latest" / "report.html").exists()
