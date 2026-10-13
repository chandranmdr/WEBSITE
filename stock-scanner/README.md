# Stock screener → scanner

A two-stage workflow for the **S&P 500 + Nasdaq-100** (about 520 stocks):

1. **Screener (end of day).** `run_screener.py` runs after the US close, filters the universe through a set of technical setups, and writes a watchlist with an entry **trigger** and a **stop** for each stock.
2. **Scanner (intraday).** `run_scanner.py` watches only that watchlist during the next session and alerts on each step: near the trigger, triggered, target hit, or stopped out.

Both can run [automatically on GitHub](#running-it-automatically-no-laptop-needed), so you get alerts on your phone without a computer switched on.

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

## Intraday scanner

```bash
python run_scanner.py --demo      # replays a simulated session in a few seconds
python run_scanner.py             # live: start any time before or during the session
open output/latest/scanner.html   # dashboard, refreshes itself every minute
```

The scanner fetches 1-minute bars for the watchlist every 60 seconds and replays the whole day each time. That means a quick spike through the trigger between two checks is still caught, and it can tell whether the stop was hit before or after the entry.

| Alert | When |
|---|---|
| 👀 Near | Price is within 0.5% below the trigger |
| 🔔 Triggered | Price trades through the trigger. The alert shows the entry, stop, a 2R target and the time-of-day-adjusted relative volume, and flags *weak volume* or *below VWAP* |
| 🎯 Target | Price reaches entry + 2 × risk |
| 🛑 Stopped | Price hits the stop after the entry |
| ⏫ Gapped | The stock opened more than 1% above the trigger, so it isn't chased |
| ✖️ Invalidated | Price traded below the stop before triggering, so the setup is off for the day |

Each alert fires once per setup per day. You can tune the thresholds and choose alert channels in the `scanner:` section of `config.yaml`.

### Alert channels

`console` and `logfile` work with no setup. `desktop` shows a Mac or Linux pop-up. For your phone:

**Telegram** (recommended: free, instant, works anywhere)
1. In Telegram, message **@BotFather**, send `/newbot`, and copy the token it gives you.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}`.
3. Put both in `.env` (copy `.env.example`) to run locally, or into GitHub secrets (see below).

**Email:** fill in the `SMTP_*` values in `.env`. For Gmail, use an [App Password](https://myaccount.google.com/apppasswords).

Then run `python run_scanner.py --alerts telegram,desktop`, or set `alerts:` in `config.yaml`.

## Running it automatically (no laptop needed)

`.github/workflows/stock-scanner.yml` runs everything on GitHub's servers. It is free for this public repo.

| Job | When (UTC = UK winter time; add 1h for UK summer time) | What |
|---|---|---|
| screen | 21:35, Mon–Fri | Runs the screener, sends tonight's watchlist to Telegram, and saves it for tomorrow |
| scan (am) | 13:20 → 18:58 | Waits for the open, then scans every minute |
| scan (pm) | 18:50 → close | Takes over from the morning job with no gaps or repeat alerts |

GitHub stops any single job after 6 hours, and the session lasts 6.5, so the scanner runs as two jobs.

**One-time setup**

1. Merge this branch into `main`. GitHub only runs scheduled workflows from the default branch.
2. Go to **Settings → Secrets and variables → Actions** and add the secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, plus the `SMTP_*` and `ALERT_EMAIL_TO` values if you want email.
3. Optional: on the *Variables* tab, set `ALERT_CHANNELS` to `telegram,email`. The default is `telegram`.
4. Go to **Actions → Stock scanner → Run workflow → screen** to test it now. You should get a Telegram message within a couple of minutes.

The HTML report and the scanner dashboard are attached to each run under *Artifacts*.

Because the repo is public, anyone can read the Actions logs, so the workflow never prints watchlists or alerts to them. They only go to your private channels. Secrets are never shown in logs.

**Caveats:** GitHub's scheduled runs can start 5–15 minutes late at busy times. Yahoo Finance sometimes rate-limits cloud servers. If either becomes a problem, a $5/month server (Hetzner, DigitalOcean) or a Raspberry Pi at home can run the same two commands from cron:

```
35 22 * * 1-5  cd ~/stock-scanner && .venv/bin/python run_screener.py --alerts telegram
25 14 * * 1-5  cd ~/stock-scanner && .venv/bin/python run_scanner.py --alerts telegram
```

The cron times are in the server's local time; set it to Europe/London.

## Tests

```bash
pip install pytest && python -m pytest tests
```

## Data notes

- **Prices:** Yahoo Finance through `yfinance`. It is free and adjusted for splits and dividends, but unofficial, so it occasionally breaks or rate-limits. `screener/data.py` is the only file to change if you move to Polygon, Alpaca, Tiingo or IBKR.
- **Index members:** fetched live from Wikipedia, with a GitHub dataset as a second source for the S&P 500. The bundled lists in `data/` are only a fallback. The Nasdaq-100 fallback is a point-in-time snapshot and will drift as the index changes.

## Roadmap

- [x] End-of-day screener with configurable setups, watchlist, and HTML report
- [x] Intraday scanner with Telegram, email and desktop alerts, plus a live dashboard
- [x] Runs automatically on GitHub Actions
- [ ] Market-regime filter (for example, only take long setups when SPY is above its 50-day MA)
- [ ] Backtest each setup on history to see which ones actually have an edge
- [ ] Publish `report.html` to the website

*For research and education only; not investment advice.*
