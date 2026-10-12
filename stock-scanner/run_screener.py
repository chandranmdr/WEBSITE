#!/usr/bin/env python3
"""End-of-day stock screener for the S&P 500 + Nasdaq-100.

    python run_screener.py              # live data, after the US close
    python run_screener.py --demo       # synthetic prices, no network needed
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from screener.data import demo_daily, download_daily
from screener.indicators import snapshot
from screener.report import write_outputs
from screener.rules import load_config, run_setups
from screener.universe import load_universe

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=HERE / "config.yaml", type=Path)
    p.add_argument("--out", default=HERE / "output", type=Path)
    p.add_argument("--demo", action="store_true", help="use synthetic prices (implies --offline)")
    p.add_argument("--offline", action="store_true", help="use the bundled index lists instead of fetching them")
    p.add_argument("--no-cache", action="store_true", help="re-download prices even if cached today")
    p.add_argument("--symbols", help="comma-separated tickers to screen instead of the indexes")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    config = load_config(args.config)
    universe = load_universe(config.universe, offline=args.offline or args.demo)
    if args.symbols:
        wanted = {s.strip().upper() for s in args.symbols.split(",")}
        universe = universe[universe["symbol"].isin(wanted)]
    symbols = universe["symbol"].tolist()
    print(f"Universe: {len(symbols)} stocks ({', '.join(config.universe)})")

    prices = demo_daily(symbols) if args.demo else download_daily(symbols, use_cache=not args.no_cache)
    print(f"Price history: {len(prices)} stocks")

    snap = snapshot(prices)
    if snap.empty:
        print("No stocks with enough history to screen.", file=sys.stderr)
        return 1
    snap = snap.merge(universe, on="symbol", how="left")
    as_of = snap["date"].max()

    hits = run_setups(snap, config)
    passed_base = len(snap.query(config.base_filter, engine="python")) if config.base_filter else len(snap)
    out = write_outputs(hits, config, args.out, as_of, len(snap), passed_base)

    print(f"\nAs of {as_of}: {passed_base} stocks pass the base filter\n")
    for s in config.setups:
        g = hits[hits["setup"] == s.name]
        names = ", ".join(g["symbol"].head(10)) + (" ..." if len(g) > 10 else "")
        print(f"  {s.name:<22} {len(g):>3}  {names}")
    print(f"\nWatchlist: {hits['symbol'].nunique()} unique symbols")
    print(f"Report:    {out / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
