"""A small self-refreshing HTML page showing every watched setup and where price is relative to it."""
from __future__ import annotations

import html
from pathlib import Path

from .scanner import STATUS_ORDER, Status

LABELS = {"waiting": "Waiting", "near": "Near trigger", "triggered": "Triggered", "target": "Target hit",
          "stopped": "Stopped out", "gapped": "Gapped over", "invalidated": "Invalidated"}
SORT = {"triggered": 0, "near": 1, "target": 2, "waiting": 3, "stopped": 4, "gapped": 5, "invalidated": 6}


def write_dashboard(statuses: list[Status], watchlist: dict, path: Path, as_of: str, refresh: int = 60) -> None:
    names = {i["symbol"]: i.get("name", "") for i in watchlist["symbols"]}
    rows = []
    for st in sorted(statuses, key=lambda s: (SORT[s.status], -(s.dist_pct or -99))):
        dist = "" if st.dist_pct is None else f"{st.dist_pct:+.2f}%"
        rvol = "" if st.rvol is None else f"{st.rvol:.1f}x"
        rows.append(
            f'<tr class="{st.status}"><td><a href="https://www.tradingview.com/chart/?symbol={html.escape(st.symbol)}" '
            f'target="_blank" rel="noopener">{html.escape(st.symbol)}</a></td><td>{html.escape(names.get(st.symbol, ""))}</td>'
            f"<td>{html.escape(st.setup.replace('_', ' '))}</td><td><span class=\"pill\">{LABELS[st.status]}</span></td>"
            f"<td>{st.last or ''}</td><td>{st.trigger}</td><td>{dist}</td><td>{st.stop}</td><td>{st.target or ''}</td>"
            f"<td>{rvol}</td><td>{st.time or ''}</td><td>{html.escape(', '.join(st.flags))}</td></tr>"
        )
    counts = {k: sum(1 for s in statuses if s.status == k) for k in STATUS_ORDER}
    summary = " · ".join(f"{v} {LABELS[k].lower()}" for k, v in counts.items() if v)
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{meta_refresh}
<title>Intraday Scanner</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --line:#e7e5e4; --card:#fff; --accent:#1d4ed8;
  --trig:#dcfce7; --trig-fg:#166534; --near:#fef9c3; --near-fg:#854d0e; --stop:#fee2e2; --stop-fg:#991b1b; --tgt:#dbeafe; --tgt-fg:#1e40af; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --line:#292524; --card:#1c1917; --accent:#93c5fd;
  --trig:#14532d; --trig-fg:#bbf7d0; --near:#713f12; --near-fg:#fef08a; --stop:#7f1d1d; --stop-fg:#fecaca; --tgt:#1e3a8a; --tgt-fg:#bfdbfe; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,-apple-system,sans-serif; }}
main {{ max-width:1200px; margin:0 auto; }} h1 {{ margin:0 0 4px; font-size:24px; }} .meta {{ color:var(--muted); margin:0 0 16px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
th,td {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
th:nth-child(-n+4),td:nth-child(-n+4),td:last-child {{ text-align:left; }}
td:nth-child(2) {{ max-width:170px; overflow:hidden; text-overflow:ellipsis; color:var(--muted); }}
a {{ color:var(--accent); font-weight:600; text-decoration:none; }}
.pill {{ font-size:12px; padding:2px 8px; border-radius:99px; background:var(--line); }}
.triggered .pill {{ background:var(--trig); color:var(--trig-fg); }} .near .pill {{ background:var(--near); color:var(--near-fg); }}
.stopped .pill,.invalidated .pill {{ background:var(--stop); color:var(--stop-fg); }} .target .pill {{ background:var(--tgt); color:var(--tgt-fg); }}
.gapped,.invalidated {{ opacity:.6; }}
</style></head><body><main>
<h1>Intraday scanner</h1>
<p class="meta">Updated {html.escape(as_of)} · watchlist from {html.escape(watchlist['as_of'])} screen · {html.escape(summary)}</p>
<div class="card"><table><thead><tr><th>Symbol</th><th>Name</th><th>Setup</th><th>Status</th><th>Last</th><th>Trigger</th>
<th>vs trigger</th><th>Stop</th><th>Target</th><th>RVOL</th><th>Time</th><th>Notes</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="meta">Delayed data from Yahoo Finance. Not investment advice.</p>
</main></body></html>""")
