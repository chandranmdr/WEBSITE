"""Build the ticker universe: S&P 500 + Nasdaq-100.

Live lists are pulled from Wikipedia (S&P 500 also from a GitHub dataset).
If every live source fails, the bundled CSVs in data/ are used instead.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (stock-screener)"}

SP500_SOURCES = [
    ("wikipedia", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"),
    ("github", "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"),
]
NDX_SOURCES = [
    ("wikipedia", "https://en.wikipedia.org/wiki/Nasdaq-100"),
]


def _get(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def _normalise(df: pd.DataFrame, symbol_col: str, name_col: str, sector_col: str | None) -> pd.DataFrame:
    out = pd.DataFrame({
        "symbol": df[symbol_col].astype(str).str.strip().str.upper(),
        "name": df[name_col].astype(str).str.strip(),
        "sector": df[sector_col].astype(str).str.strip() if sector_col else "",
    })
    return out[out["symbol"].str.len() > 0]


def _find_table(html: str, symbol_cols: tuple[str, ...]) -> pd.DataFrame:
    for table in pd.read_html(io.StringIO(html)):
        cols = {str(c) for c in table.columns}
        sym = next((c for c in symbol_cols if c in cols), None)
        if sym and len(table) >= 90:
            name = "Security" if "Security" in cols else "Company"
            sector = next((c for c in ("GICS Sector", "ICB Industry[14]", "ICB Industry") if c in cols), None)
            return _normalise(table, sym, name, sector)
    raise ValueError("constituent table not found")


def load_sp500() -> pd.DataFrame:
    for name, url in SP500_SOURCES:
        try:
            if name == "wikipedia":
                df = _find_table(_get(url), ("Symbol",))
            else:
                df = _normalise(pd.read_csv(io.StringIO(_get(url))), "Symbol", "Security", "GICS Sector")
            if len(df) >= 480:
                log.info("S&P 500: %d tickers from %s", len(df), name)
                return df
        except Exception as exc:  # noqa: BLE001 - any failure falls through to the next source
            log.warning("S&P 500 source %s failed: %s", name, exc)
    log.warning("S&P 500: using bundled fallback list")
    return pd.read_csv(DATA_DIR / "sp500_fallback.csv").fillna("")


def load_nasdaq100() -> pd.DataFrame:
    for name, url in NDX_SOURCES:
        try:
            df = _find_table(_get(url), ("Ticker", "Symbol"))
            if len(df) >= 95:
                log.info("Nasdaq-100: %d tickers from %s", len(df), name)
                return df
        except Exception as exc:  # noqa: BLE001
            log.warning("Nasdaq-100 source %s failed: %s", name, exc)
    log.warning("Nasdaq-100: using bundled fallback list")
    return pd.read_csv(DATA_DIR / "nasdaq100_fallback.csv").fillna("")


def load_universe(indexes: list[str], offline: bool = False) -> pd.DataFrame:
    """Return one row per symbol with columns symbol, name, sector, indexes."""
    loaders = {
        "sp500": (load_sp500, "sp500_fallback.csv"),
        "nasdaq100": (load_nasdaq100, "nasdaq100_fallback.csv"),
    }
    frames = []
    for idx in indexes:
        loader, fallback = loaders[idx]
        df = pd.read_csv(DATA_DIR / fallback).fillna("") if offline else loader()
        frames.append(df.assign(index=idx))
    combined = pd.concat(frames, ignore_index=True)
    # Prefer the GICS sector from the S&P list when a stock is in both indexes.
    combined["sector"] = combined["sector"].replace("", pd.NA)
    universe = (
        combined.groupby("symbol", as_index=False)
        .agg(name=("name", "first"), sector=("sector", "first"), indexes=("index", lambda s: ",".join(sorted(set(s)))))
    )
    universe["sector"] = universe["sector"].fillna("")
    return universe.sort_values("symbol").reset_index(drop=True)
