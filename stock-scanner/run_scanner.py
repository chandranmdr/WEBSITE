#!/usr/bin/env python3
"""Intraday scanner: watches the screener's watchlist and alerts on trigger, stop and target.

    python run_scanner.py                 # run all session, poll every minute (laptop / server)
    python run_scanner.py --once          # one pass, alert on what changed in the last N minutes (cron / GitHub Actions)
    python run_scanner.py --demo          # replay a simulated session in a few seconds
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time as clock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from screener.intraday import CLOSE, NY, OPEN, DemoFeed, YahooFeed
from screener.notify import Notifier, load_dotenv
from screener.scanner import ScanParams, format_alert, new_alerts, scan
from screener.dashboard import write_dashboard

HERE = Path(__file__).resolve().parent
log = logging.getLogger("scanner")


def load_scanner_config(path: Path) -> tuple[ScanParams, list[str], int]:
    raw = (yaml.safe_load(path.read_text()) or {}).get("scanner", {})
    params = ScanParams(**{k: raw[k] for k in ("near_pct", "max_gap_pct", "target_r", "min_rvol") if k in raw})
    return params, raw.get("alerts", ["console", "logfile"]), int(raw.get("poll_seconds", 60))


def truncate(bars: dict, before: datetime) -> dict:
    return {s: df[df.index < before] for s, df in bars.items()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--watchlist", default=HERE / "output" / "latest" / "watchlist.json", type=Path)
    p.add_argument("--config", default=HERE / "config.yaml", type=Path)
    p.add_argument("--out", default=HERE / "output" / "latest", type=Path, help="where scanner.html and alerts.log go")
    p.add_argument("--once", action="store_true", help="single pass for schedulers")
    p.add_argument("--lookback", type=int, default=15, help="--once: alert on changes within this many minutes")
    p.add_argument("--stop-at", help="loop mode: exit at this UTC time (HH:MM), e.g. to stay inside a CI job limit")
    p.add_argument("--resume-from", help="loop mode: treat everything before this UTC time (HH:MM) as already alerted")
    p.add_argument("--demo", action="store_true", help="simulated session (no network)")
    p.add_argument("--alerts", help="comma-separated channels, overrides config (console,logfile,desktop,telegram,email)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    load_dotenv(HERE / ".env")

    if not args.watchlist.exists():
        print(f"No watchlist at {args.watchlist}. Run run_screener.py first.", file=sys.stderr)
        return 1
    watchlist = json.loads(args.watchlist.read_text())
    params, channels, poll = load_scanner_config(args.config)
    if args.alerts:
        channels = [c.strip() for c in args.alerts.split(",")]
    notifier = Notifier(channels, args.out / "alerts.log")
    names = {i["symbol"]: i.get("name", "") for i in watchlist["symbols"]}
    symbols = list(names)

    age = (date.today() - date.fromisoformat(watchlist["as_of"])).days
    if age > 4 and not args.demo:
        log.warning("Watchlist is %d days old (as of %s)", age, watchlist["as_of"])
    print(f"Watching {len(symbols)} symbols / {sum(len(i['setups']) for i in watchlist['symbols'])} setups "
          f"from the {watchlist['as_of']} screen · alerts: {', '.join(channels)}")

    feed = DemoFeed(watchlist) if args.demo else YahooFeed(symbols)

    def emit(alerts):
        for st in alerts:
            text = format_alert(st, names.get(st.symbol, ""))
            notifier.send(f"{st.symbol} {st.status}", text)

    if args.once:
        now = feed.now()
        if not args.demo and not (OPEN <= now.time() <= (datetime.combine(now.date(), CLOSE) + timedelta(minutes=5)).time()):
            print("Market is closed; nothing to do.")
            return 0
        bars = feed.fetch()
        if not bars:
            print("No intraday data (holiday?).")
            return 0
        last_bar = max(df.index[-1] for df in bars.values())
        # Stateless dedup: what did the picture look like `lookback` minutes ago?
        seen: dict[str, str] = {}
        new_alerts(scan(watchlist, truncate(bars, last_bar - timedelta(minutes=args.lookback - 1)), params), seen)
        statuses = scan(watchlist, bars, params)
        emit(new_alerts(statuses, seen))
        write_dashboard(statuses, watchlist, args.out / "scanner.html", _ts(last_bar), refresh=0)
        return 0

    seen: dict[str, str] = {}
    primed = not args.resume_from
    stop_at = _utc_today(args.stop_at) if args.stop_at else None
    while True:
        now = feed.now()
        if stop_at and now >= stop_at:
            print("Reached --stop-at; handing over.")
            return 0
        if not args.demo:
            if now.weekday() >= 5:
                print("Weekend; markets closed.")
                return 0
            if now.time() < OPEN:
                wait = (datetime.combine(now.date(), OPEN, NY) - now).total_seconds()
                print(f"Waiting {wait / 60:.0f} min for the open...")
                clock.sleep(min(wait, 600))
                continue
            if now.time() > CLOSE:
                print("Session over.")
                return 0
        try:
            bars = feed.fetch()
        except Exception as exc:  # noqa: BLE001 - network hiccup: try again next poll
            log.warning("Fetch failed: %s", exc)
            clock.sleep(poll)
            continue
        if not bars and not args.demo and now.time().hour >= 10:
            print("No intraday data an hour after the open; market holiday?")
            return 0
        if not primed and bars:
            # A previous job already alerted on everything before this time.
            new_alerts(scan(watchlist, truncate(bars, _utc_today(args.resume_from)), params), seen)
            primed = True
        statuses = scan(watchlist, bars, params)
        emit(new_alerts(statuses, seen))
        write_dashboard(statuses, watchlist, args.out / "scanner.html", _ts(feed.now()), refresh=poll)
        if args.demo:
            if feed.finished:
                break
            continue
        clock.sleep(poll)

    counts = {}
    for st in statuses:
        counts[st.status] = counts.get(st.status, 0) + 1
    print("\nEnd of session: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    print(f"Dashboard: {args.out / 'scanner.html'}")
    return 0


def _utc_today(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.now(timezone.utc).replace(hour=h, minute=m, second=0, microsecond=0)


def _ts(t) -> str:
    return t.strftime("%Y-%m-%d %H:%M ET")


if __name__ == "__main__":
    raise SystemExit(main())
