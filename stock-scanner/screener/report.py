"""Write the screener results: CSV, watchlist JSON (input for the scanner), and an HTML report."""
from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pandas as pd

from .rules import Config

TABLE_COLS = ["rank", "symbol", "name", "sector", "close", "chg_pct", "rvol", "rsi14", "rs_rank",
              "pct_from_high252", "trigger", "stop", "risk_pct"]
CSV_COLS = ["date", "setup", *TABLE_COLS[:4], "indexes", *TABLE_COLS[4:], "atr14", "sma50", "sma200", "dollar_vol20"]


def build_watchlist(hits: pd.DataFrame, as_of: str) -> dict:
    """Group hits by symbol: this is what the intraday scanner will watch."""
    items = []
    for sym, g in hits.groupby("symbol", sort=False):
        first = g.iloc[0]
        items.append({
            "symbol": sym,
            "name": first.get("name", ""),
            "sector": first.get("sector", ""),
            "close": round(float(first["close"]), 2),
            "atr14": round(float(first["atr14"]), 2),
            "avg_vol50": int(first["avg_vol50"]),
            "rs_rank": int(first["rs_rank"]),
            "setups": [
                {"setup": r.setup, "trigger": float(r.trigger), "stop": float(r.stop), "risk_pct": float(r.risk_pct)}
                for r in g.itertuples()
            ],
        })
    items.sort(key=lambda x: (-len(x["setups"]), -x["rs_rank"]))
    return {"as_of": as_of, "count": len(items), "symbols": items}


def _fmt(col: str, val) -> str:
    if pd.isna(val):
        return ""
    if col in ("chg_pct", "pct_from_high252", "risk_pct"):
        return f"{val:+.1f}%" if col != "risk_pct" else f"{val:.1f}%"
    if col in ("rank", "rs_rank"):
        return str(int(val))
    if col == "rvol":
        return f"{val:.1f}x"
    if isinstance(val, float):
        return f"{val:,.2f}"
    return html.escape(str(val))


def render_html(hits: pd.DataFrame, config: Config, as_of: str, universe_size: int, passed_base: int) -> str:
    sections = []
    for s in config.setups:
        g = hits[hits["setup"] == s.name]
        head = "".join(f"<th>{c.replace('_', ' ')}</th>" for c in TABLE_COLS)
        if g.empty:
            body = f'<tr><td colspan="{len(TABLE_COLS)}" class="empty">No matches today</td></tr>'
        else:
            rows = []
            for _, r in g.iterrows():
                cells = []
                for c in TABLE_COLS:
                    v = _fmt(c, r.get(c))
                    if c == "symbol":
                        v = f'<a href="https://www.tradingview.com/chart/?symbol={html.escape(r.symbol)}" target="_blank" rel="noopener">{v}</a>'
                    cls = ' class="neg"' if c == "chg_pct" and r.get(c, 0) < 0 else (' class="pos"' if c == "chg_pct" else "")
                    cells.append(f"<td{cls}>{v}</td>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
            body = "\n".join(rows)
        sections.append(f"""
<section>
  <h2>{html.escape(s.name.replace('_', ' '))} <span class="count">{len(g)}</span></h2>
  <p class="desc">{html.escape(s.description)}</p>
  <code>{html.escape(s.condition)}</code>
  <div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
</section>""")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EOD Screener {as_of}</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --line:#e7e5e4; --card:#fff; --pos:#15803d; --neg:#b91c1c; --accent:#1d4ed8; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --line:#292524; --card:#1c1917; --pos:#4ade80; --neg:#f87171; --accent:#93c5fd; }} }}
body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:14px/1.5 system-ui,-apple-system,sans-serif; }}
main {{ max-width:1200px; margin:0 auto; }}
h1 {{ margin:0 0 4px; font-size:24px; }} h2 {{ margin:0; font-size:17px; text-transform:capitalize; }}
.meta,.desc {{ color:var(--muted); margin:4px 0 8px; }}
section {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:16px 0; }}
.count {{ font-size:12px; background:var(--line); border-radius:99px; padding:1px 8px; margin-left:6px; vertical-align:middle; }}
code {{ display:block; font-size:12px; color:var(--muted); margin-bottom:10px; white-space:pre-wrap; }}
.scroll {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }}
th,td {{ padding:6px 8px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
th {{ color:var(--muted); font-weight:600; font-size:12px; text-transform:uppercase; }}
th:nth-child(-n+4),td:nth-child(-n+4) {{ text-align:left; }}
td:nth-child(3) {{ max-width:180px; overflow:hidden; text-overflow:ellipsis; }}
a {{ color:var(--accent); font-weight:600; text-decoration:none; }}
.pos {{ color:var(--pos); }} .neg {{ color:var(--neg); }} .empty {{ text-align:center; color:var(--muted); }}
</style></head><body><main>
<h1>End-of-day screener</h1>
<p class="meta">Data as of {as_of} · {universe_size} stocks in S&amp;P 500 + Nasdaq-100 · {passed_base} pass base filter
<code>{html.escape(config.base_filter)}</code></p>
{''.join(sections)}
<p class="meta">Trigger = entry alert level for the next session; stop = where the setup is invalidated. Not investment advice.</p>
</main></body></html>"""


def write_outputs(hits: pd.DataFrame, config: Config, out_dir: Path, as_of: str, universe_size: int, passed_base: int) -> Path:
    day_dir = out_dir / as_of
    day_dir.mkdir(parents=True, exist_ok=True)

    cols = [c for c in CSV_COLS if c in hits.columns]
    hits[cols].to_csv(day_dir / "screen.csv", index=False, float_format="%.4g")
    (day_dir / "watchlist.json").write_text(json.dumps(build_watchlist(hits, as_of), indent=2))
    (day_dir / "report.html").write_text(render_html(hits, config, as_of, universe_size, passed_base))

    latest = out_dir / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(day_dir, latest)
    return day_dir
