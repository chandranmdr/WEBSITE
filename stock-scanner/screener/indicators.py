"""Technical indicators in plain pandas (no TA-Lib needed)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of an OHLCV frame with indicator columns added."""
    d = df.copy()
    c, h, l, v = d["close"], d["high"], d["low"], d["volume"]

    for n in (10, 20, 50, 200):
        d[f"sma{n}"] = sma(c, n)
    d["ema21"] = ema(c, 21)
    d["rsi2"] = rsi(c, 2)
    d["rsi14"] = rsi(c, 14)
    d["atr14"] = atr(d, 14)
    d["atr_pct"] = d["atr14"] / c * 100

    # Volume: today vs the 50 prior sessions (excluding today).
    d["avg_vol50"] = v.shift().rolling(50, min_periods=20).mean()
    d["rvol"] = v / d["avg_vol50"]
    d["dollar_vol20"] = (c * v).rolling(20, min_periods=20).mean()

    # Prior highs/lows exclude today, so "close > high20" means a fresh breakout.
    d["high20"] = h.shift().rolling(20, min_periods=20).max()
    d["low20"] = l.shift().rolling(20, min_periods=20).min()
    # The recent box, including today: used as entry/stop levels for tight ranges.
    d["high10"] = h.rolling(10, min_periods=10).max()
    d["low10"] = l.rolling(10, min_periods=10).min()
    d["high252"] = h.rolling(252, min_periods=200).max()
    d["low252"] = l.rolling(252, min_periods=200).min()
    d["pct_from_high252"] = (c / d["high252"] - 1) * 100

    for n in (5, 21, 63, 126, 252):
        d[f"ret{n}"] = (c / c.shift(n) - 1) * 100

    d["chg_pct"] = c.pct_change() * 100
    d["gap_pct"] = (d["open"] / c.shift() - 1) * 100
    d["dist_sma20"] = (c / d["sma20"] - 1) * 100
    d["dist_sma50"] = (c / d["sma50"] - 1) * 100
    d["dist_sma200"] = (c / d["sma200"] - 1) * 100
    d["sma200_slope"] = (d["sma200"] / d["sma200"].shift(20) - 1) * 100

    rng = h - l
    d["close_pos"] = ((c - l) / rng.replace(0, np.nan)).fillna(0.5)  # 0 = closed at low, 1 = at high
    d["nr7"] = rng <= rng.rolling(7, min_periods=7).min()
    d["inside_day"] = (h <= h.shift()) & (l >= l.shift())
    # Volatility contraction: 10-day range vs 50-day range.
    d["range10_vs_50"] = (h.rolling(10).max() - l.rolling(10).min()) / (h.rolling(50).max() - l.rolling(50).min())

    d["low2"] = l.rolling(2).min()
    return d


def snapshot(prices: dict[str, pd.DataFrame], min_history: int = 210) -> pd.DataFrame:
    """One row per symbol holding its latest bar plus indicators, and cross-sectional ranks."""
    rows = []
    for sym, df in prices.items():
        if len(df) < min_history:
            continue
        last = add_indicators(df).iloc[-1]
        rows.append(last.rename(sym))
    snap = pd.DataFrame(rows).infer_objects()
    snap.index.name = "symbol"
    if snap.empty:
        return snap

    snap["date"] = [prices[s].index[-1].date().isoformat() for s in snap.index]

    # IBD-style relative strength: weighted 3/6/12-month returns, ranked 1-99 across the universe.
    rs_raw = 0.4 * snap["ret63"] + 0.2 * snap["ret126"].fillna(snap["ret63"]) + 0.4 * snap["ret252"].fillna(snap["ret126"])
    snap["rs_rank"] = (rs_raw.rank(pct=True) * 98 + 1).round()
    return snap.reset_index()
