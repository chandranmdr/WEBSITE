"""Intraday scanner logic: turn today's 1-minute bars into a status per (symbol, setup).

Evaluation replays the bars in order, so the result doesn't depend on how often
we poll: a spike through the trigger between two polls is still caught, and we
know whether the stop was hit before or after the entry.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from .intraday import expected_volume_fraction, minutes_since_open

# Higher = further along. Alerts fire only when a setup moves forward.
STATUS_ORDER = {"waiting": 0, "near": 1, "gapped": 2, "invalidated": 2, "triggered": 3, "target": 4, "stopped": 4}
ALERT_STATUSES = {"near", "gapped", "invalidated", "triggered", "target", "stopped"}


@dataclass
class ScanParams:
    near_pct: float = 0.5          # heads-up when within this % below the trigger
    max_gap_pct: float = 1.0       # opening more than this % above the trigger = gapped, no entry
    target_r: float = 2.0          # target = entry + target_r * (entry - stop)
    min_rvol: float = 1.0          # triggers below this time-adjusted relative volume are flagged "weak volume"


@dataclass
class Status:
    symbol: str
    setup: str
    trigger: float
    stop: float
    status: str = "waiting"
    last: float | None = None
    dist_pct: float | None = None      # last price vs trigger, %
    time: str | None = None            # when the current status was reached (HH:MM ET)
    entry: float | None = None
    target: float | None = None
    rvol: float | None = None          # at trigger time, adjusted for time of day
    above_vwap: bool | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.symbol}:{self.setup}"

    def to_dict(self) -> dict:
        return asdict(self)


def _hhmm(ts: pd.Timestamp) -> str:
    return ts.strftime("%H:%M")


def evaluate(item: dict, setup: dict, bars: pd.DataFrame | None, p: ScanParams) -> Status:
    trig, stop = float(setup["trigger"]), float(setup["stop"])
    st = Status(symbol=item["symbol"], setup=setup["setup"], trigger=trig, stop=stop)
    if bars is None or bars.empty:
        return st

    st.last = round(float(bars["close"].iloc[-1]), 2)
    st.dist_pct = round((st.last / trig - 1) * 100, 2)
    first_open = float(bars["open"].iloc[0])

    if first_open > trig * (1 + p.max_gap_pct / 100):
        st.status, st.time = "gapped", _hhmm(bars.index[0])
        st.flags.append(f"opened {((first_open / trig) - 1) * 100:.1f}% above trigger")
        return st
    if first_open <= stop:
        st.status, st.time = "invalidated", _hhmm(bars.index[0])
        st.flags.append("opened below stop")
        return st

    hit = bars.index[bars["high"] >= trig]
    if len(hit) == 0:
        broke = bars.index[bars["low"] <= stop]
        if len(broke):
            st.status, st.time = "invalidated", _hhmm(broke[0])
        elif st.dist_pct >= -p.near_pct:
            st.status, st.time = "near", _hhmm(bars.index[-1])
        return st

    t_entry = hit[0]
    before = bars.loc[:t_entry].iloc[:-1]
    if (before["low"] <= stop).any():
        st.status, st.time = "invalidated", _hhmm(before.index[before["low"] <= stop][0])
        return st

    i = bars.index.get_loc(t_entry)
    entry = max(trig, float(bars["open"].iloc[i]))
    st.status, st.time, st.entry = "triggered", _hhmm(t_entry), round(entry, 2)
    risk = entry - stop
    st.target = round(entry + p.target_r * risk, 2)

    upto = bars.iloc[: i + 1]
    expected = item["avg_vol50"] * expected_volume_fraction(minutes_since_open(t_entry))
    st.rvol = round(float(upto["volume"].sum()) / expected, 2) if expected > 0 else None
    typical = (upto["high"] + upto["low"] + upto["close"]) / 3
    vwap = float((typical * upto["volume"]).sum() / upto["volume"].sum()) if upto["volume"].sum() > 0 else entry
    st.above_vwap = entry >= vwap
    if st.rvol is not None and st.rvol < p.min_rvol:
        st.flags.append("weak volume")
    if not st.above_vwap:
        st.flags.append("below VWAP")

    # After the entry bar: whichever of stop / target comes first. Same bar counts as stopped (conservative).
    after = bars.iloc[i + 1 :]
    stop_hits = after.index[after["low"] <= stop]
    tgt_hits = after.index[after["high"] >= st.target]
    first_stop = stop_hits[0] if len(stop_hits) else None
    first_tgt = tgt_hits[0] if len(tgt_hits) else None
    if first_stop is not None and (first_tgt is None or first_stop <= first_tgt):
        st.status, st.time = "stopped", _hhmm(first_stop)
    elif first_tgt is not None:
        st.status, st.time = "target", _hhmm(first_tgt)
    return st


def scan(watchlist: dict, bars: dict[str, pd.DataFrame], p: ScanParams) -> list[Status]:
    return [evaluate(item, s, bars.get(item["symbol"]), p) for item in watchlist["symbols"] for s in item["setups"]]


def new_alerts(statuses: list[Status], seen: dict[str, str]) -> list[Status]:
    """Statuses that moved forward since last time; updates `seen` in place."""
    out = []
    for st in statuses:
        prev = seen.get(st.key, "waiting")
        if st.status in ALERT_STATUSES and st.status != prev and STATUS_ORDER[st.status] > STATUS_ORDER[prev]:
            out.append(st)
        if STATUS_ORDER[st.status] >= STATUS_ORDER[prev]:
            seen[st.key] = st.status
    return out


ICONS = {"near": "👀", "triggered": "🔔", "target": "🎯", "stopped": "🛑", "gapped": "⏫", "invalidated": "✖️"}


def format_alert(st: Status, name: str = "") -> str:
    head = f"{ICONS.get(st.status, '')} {st.symbol} {st.status.upper()} ({st.setup.replace('_', ' ')}) {st.time} ET"
    if st.status == "near":
        body = f"last {st.last} is {abs(st.dist_pct):.2f}% below trigger {st.trigger}"
    elif st.status == "triggered":
        risk = (st.entry - st.stop) / st.entry * 100
        bits = [f"entry {st.entry} · stop {st.stop} ({risk:.1f}% risk) · target {st.target}"]
        if st.rvol is not None:
            bits.append(f"RVOL {st.rvol:.1f}x")
        body = " · ".join(bits)
    elif st.status == "target":
        body = f"hit {st.target} (entry {st.entry})"
    elif st.status == "stopped":
        body = f"hit stop {st.stop} after entry {st.entry}"
    elif st.status == "invalidated":
        body = f"below stop {st.stop} before triggering; setup off for today"
    else:
        body = f"trigger {st.trigger}; not chasing"
    flags = f" [{', '.join(st.flags)}]" if st.flags else ""
    return f"{head}{' ' + name if name else ''}\n   {body}{flags}"
