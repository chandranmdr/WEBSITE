# Stock screener → scanner

A two-stage workflow for the **S&P 500 + Nasdaq-100** (about 520 stocks):

1. **Screener (end of day, built).** It runs after the US close, filters the universe through a set of technical setups, and writes a watchlist with an entry **trigger** and a **stop** for each stock.
2. **Scanner (intraday, next step).** It watches only that watchlist during the next session and alerts when price crosses a trigger.

## Quick start

```bash
cd stock-scanner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run_screener.py --demo     # synthetic prices: checks the install, no network
python run_screener.py            # real data (Yahoo Finance), run after 4pm ET / 9pm UK
open output/latest/report.html
```

The first real run downloads two years of daily bars for every stock, which takes about a minute. Prices are cached in `cache/` for the rest of the day, so you can tweak `config.yaml` and re-run straight away.

Other options:

| Flag | What it does |
|---|---|
| `--symbols AAPL,MSFT,NVDA` | Screen only these tickers |
| `--offline` | Use the bundled index lists in `data/` instead of fetching them |
| `--no-cache` | Force a fresh price download |
| `--config other.yaml` | Use a different set of rules |
| `-v` | Verbose logging |

## Output

Each run writes to `output/<date>/`, and also copies the results to `output/latest/`:

- `report.html`: one table per setup, with chart links to TradingView
- `screen.csv`: every hit with its indicators, ready for Excel
- `watchlist.json`: unique symbols, each with its setups, trigger, stop and risk %. **This is the scanner's input.**

## The setups (`config.yaml`)

All setups run after a base filter: price ≥ $10 and an average daily dollar volume ≥ $25M.

| Setup | Idea | Trigger / stop |
|---|---|---|
| `trend_pullback` | Above a rising 200-day MA, pulled back to the 50-day MA, RSI(14) < 45 | today's high / 2-day low |
| `breakout_20d` | Closes above the prior 20-day high on ≥ 1.5× volume, near the day's high | today's high / close − 1.5 ATR |
| `near_high_tight` | Within 5% of its 52-week high, tight 10-day range, RS rank ≥ 80 | 10-day high / 10-day low |
| `oversold_in_uptrend` | RSI(2) < 10 while above a rising 200-day MA (Connors-style) | today's high / close − 2 ATR |
| `nr7_inside_leader` | NR7 or inside day in a strong uptrend | today's high / today's low |

`rs_rank` (1–99) is relative strength against the rest of the universe. It weights 3-, 6- and 12-month returns, IBD-style.

Each condition is a plain pandas expression, so you can add or change a setup without touching any code:

```yaml
  my_setup:
    description: Strong stock, quiet day
    condition: rs_rank >= 90 and atr_pct < 2 and close > ema21
    rank_by: rs_rank
    trigger: high
    stop: low2
    limit: 10
```

The full list of columns you can use is at the top of `config.yaml`.

## Running it every evening

On Mac or Linux, add a cron job with `crontab -e`. This one runs at 22:15 UK time, Monday to Friday:

```
15 22 * * 1-5 cd /path/to/stock-scanner && .venv/bin/python run_screener.py >> screener.log 2>&1
```

On Windows, use Task Scheduler to run `.venv\Scripts\python.exe run_screener.py`.

## Tests

```bash
pip install pytest && python -m pytest tests
```

## Data notes

- **Prices:** Yahoo Finance through `yfinance`. It is free and adjusted for splits and dividends, but unofficial, so it occasionally breaks or rate-limits. `screener/data.py` is the only file to change if you move to Polygon, Alpaca, Tiingo or IBKR.
- **Index members:** fetched live from Wikipedia, with a GitHub dataset as a second source for the S&P 500. The bundled lists in `data/` are only a fallback. The Nasdaq-100 fallback is a point-in-time snapshot and will drift as the index changes.

## Roadmap

- [x] End-of-day screener with configurable setups, watchlist, and HTML report
- [ ] Intraday scanner: poll or stream quotes for `watchlist.json` and alert on trigger crosses with relative volume (email, Telegram, or IBKR price alerts)
- [ ] Market-regime filter (for example, only take long setups when SPY is above its 50-day MA)
- [ ] Backtest each setup on history to see which ones actually have an edge
- [ ] Publish `report.html` to the website

*For research and education only; not investment advice.*
