"""Intraday 1-minute bars: live from Yahoo Finance, or a simulated session for demos/tests."""
from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .data import to_yahoo

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
SESSION_MINUTES = 390


def minutes_since_open(ts: pd.Timestamp) -> float:
    ts = ts.tz_convert(NY) if ts.tzinfo else ts.tz_localize(NY)
    return (ts.hour * 60 + ts.minute) - (OPEN.hour * 60 + OPEN.minute) + 1  # a bar stamped 9:30 covers minute 1


def expected_volume_fraction(minutes: float) -> float:
    """Share of a normal day's volume traded by `minutes` after the open.

    US stocks trade in a U shape: heavy at the open and into the close, quiet at
    lunch. A linear clock would make every stock look "high volume" at 9:45.
    """
    t = np.arange(1, SESSION_MINUTES + 1)
    weight = 1 + 2.5 * np.exp(-t / 20) + 1.2 * np.exp(-(SESSION_MINUTES - t) / 25)
    cum = np.cumsum(weight) / weight.sum()
    m = int(min(max(minutes, 1), SESSION_MINUTES))
    return float(cum[m - 1])


class YahooFeed:
    """Today's regular-session 1-minute bars for a list of symbols (one HTTP call per poll)."""

    def __init__(self, symbols: list[str]):
        self.symbols = symbols

    def fetch(self) -> dict[str, pd.DataFrame]:
        import yfinance as yf

        raw = yf.download([to_yahoo(s) for s in self.symbols], period="1d", interval="1m",
                          prepost=False, auto_adjust=False, group_by="ticker", threads=True, progress=False)
        out = {}
        for sym in self.symbols:
            try:
                df = raw[to_yahoo(sym)] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
            if df.empty:
                continue
            df.index = df.index.tz_convert(NY) if df.index.tz else df.index.tz_localize(NY)
            today = df.index[-1].date()
            out[sym] = df[df.index.date == today]
        return out

    def now(self) -> datetime:
        return datetime.now(NY)


class DemoFeed:
    """A simulated session built around each stock's trigger, so some trigger, some stop out.

    Every fetch() advances the clock by `step` minutes, so a whole day replays in seconds.
    """

    def __init__(self, watchlist: dict, step: int = 15, seed: int = 11, day: datetime | None = None):
        rng = np.random.default_rng(seed)
        day = (day or datetime.now(NY)).date()
        idx = pd.date_range(datetime.combine(day, OPEN, NY), periods=SESSION_MINUTES, freq="1min")
        self.bars: dict[str, pd.DataFrame] = {}
        for item in watchlist["symbols"]:
            trig = item["setups"][0]["trigger"]
            stop = item["setups"][0]["stop"]
            start = item["close"] * (1 + rng.normal(0, 0.004))
            # Drift each path toward a random destination: above trigger, between, or below stop.
            dest = rng.choice([trig * 1.015, (trig + stop) / 2, stop * 0.995, trig * 1.03])
            path = np.linspace(start, dest, SESSION_MINUTES) + np.cumsum(rng.normal(0, item["atr14"] * 0.02, SESSION_MINUTES))
            close = np.maximum(path, 0.01)
            open_ = np.r_[start, close[:-1]]
            wiggle = np.abs(rng.normal(0, item["atr14"] * 0.01, SESSION_MINUTES))
            vol_scale = item["avg_vol50"] * rng.uniform(0.6, 2.0)
            frac = np.diff([0] + [expected_volume_fraction(m) for m in range(1, SESSION_MINUTES + 1)])
            self.bars[item["symbol"]] = pd.DataFrame({
                "open": open_, "high": np.maximum(open_, close) + wiggle, "low": np.minimum(open_, close) - wiggle,
                "close": close, "volume": (vol_scale * frac).round(),
            }, index=idx)
        self.step = step
        self.cursor = 0

    def fetch(self) -> dict[str, pd.DataFrame]:
        self.cursor = min(self.cursor + self.step, SESSION_MINUTES)
        return {s: df.iloc[: self.cursor] for s, df in self.bars.items()}

    def now(self) -> datetime:
        any_df = next(iter(self.bars.values()))
        return any_df.index[max(self.cursor - 1, 0)].to_pydatetime()

    @property
    def finished(self) -> bool:
        return self.cursor >= SESSION_MINUTES
