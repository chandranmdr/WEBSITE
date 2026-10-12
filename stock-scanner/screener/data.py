"""Daily OHLCV download (Yahoo Finance via yfinance) with a per-day disk cache."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"


def to_yahoo(symbol: str) -> str:
    """BRK.B -> BRK-B (Yahoo uses dashes for share classes)."""
    return symbol.replace(".", "-")


def download_daily(symbols: list[str], period: str = "2y", batch_size: int = 100, use_cache: bool = True) -> dict[str, pd.DataFrame]:
    """Return {symbol: DataFrame[open, high, low, close, volume]} indexed by date.

    Prices are split- and dividend-adjusted. Results are cached for the day so
    re-running the screener with different rules doesn't re-download.
    """
    import yfinance as yf

    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"daily_{date.today().isoformat()}_{period}.pkl"
    cached: dict[str, pd.DataFrame] = pd.read_pickle(cache_file) if use_cache and cache_file.exists() else {}

    missing = [s for s in symbols if s not in cached]
    for i in range(0, len(missing), batch_size):
        batch = missing[i : i + batch_size]
        log.info("Downloading %d-%d of %d", i + 1, i + len(batch), len(missing))
        raw = yf.download(
            [to_yahoo(s) for s in batch],
            period=period,
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        for sym in batch:
            ysym = to_yahoo(sym)
            try:
                df = raw[ysym] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                log.warning("No data for %s", sym)
                continue
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
            if len(df):
                cached[sym] = df

    if use_cache:
        pd.to_pickle(cached, cache_file)
    return {s: cached[s] for s in symbols if s in cached}


def demo_daily(symbols: list[str], days: int = 400, seed: int = 7) -> dict[str, pd.DataFrame]:
    """Synthetic random-walk prices, for trying the pipeline without network access."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    out = {}
    for sym in symbols:
        drift = rng.normal(0.0004, 0.0008)
        rets = rng.normal(drift, rng.uniform(0.01, 0.03), days)
        close = 50 * rng.uniform(0.5, 6) * np.exp(np.cumsum(rets))
        spread = np.abs(rng.normal(0, 0.012, days)) * close
        open_ = close * (1 + rng.normal(0, 0.005, days))
        high = np.maximum(open_, close) + spread / 2
        low = np.minimum(open_, close) - spread / 2
        volume = rng.lognormal(15, 0.4, days).round()
        out[sym] = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)
    return out
