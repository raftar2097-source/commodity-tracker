# Commodity Tracker

Tracks global commodity prices and flags Indian stocks with a backtested,
statistically-validated relationship to them -- both short-horizon
(commodity spikes, does the stock react) and medium-horizon (commodity
enters a sustained trend, does a late entrant still capture a meaningful
move over the following quarter).

**Live UI:** https://raftar2097-source.github.io/commodity-tracker/
**Runs:** daily at 07:00 IST, Mon-Fri, via GitHub Actions (before NSE open)
**Cost:** $0/month -- yfinance needs no API key, GitHub Actions free tier covers the rest

## Why this exists

A raw correlation coefficient between a commodity and a stock is not
trustworthy on its own -- two things can look correlated just because both
happen to move with the broader market, and testing many candidate stocks
against one commodity will throw up false positives by chance alone. This
project only surfaces a pair once it clears several independent checks
(see "How a pair gets validated" below), and keeps the passing pairs in
`validated_pairs.json` for the daily job to scan against.

## Architecture

```
correlation_engine.py          validated_pairs.json         daily_scan.py
  (run periodically,             (curated, backtested    ->   (runs daily via
   by hand, to test new           universe -- what the         GitHub Actions,
   commodities/candidates)        daily job scans)              checks TODAY's
        |                              ^                        data against the
        | backtest results             | manually update        same thresholds
        v                              | after reviewing         used in the
   printed report                      | a new backtest          backtest)
   (correlation, reaction,                                            |
    trend-continuation)                                               v
                                                              data/<date>.json
                                                              (committed back
                                                               to the repo)
```

Two different cadences on purpose: figuring out *which* pairs are real
(`correlation_engine.py`) is expensive and only needs to happen when adding
a new commodity or re-validating an existing one. Checking whether *today*
is a signal day for an already-validated pair (`daily_scan.py`) is cheap
and needs to run every day.

## How a pair gets validated

1. **Market-beta stripping** -- regress both the commodity's and the
   stock's returns on the Nifty 50, correlate the residuals. This isolates
   the commodity-specific relationship from "both just move with the
   market," which is the single biggest source of false positives.
2. **Multi-window stability** -- the idiosyncratic correlation is
   recomputed over 30/60/90/180-day trailing windows; the sign has to be
   consistent across all of them, not just true in whichever window you
   happened to test.
3. **FDR correction** (Benjamini-Hochberg) -- when testing several
   candidate stocks against one commodity, some will look "significant" by
   chance. This correction controls for that across the whole batch of
   tests, not per-pair.
4. **Two independent behavioral studies**, since correlation alone doesn't
   answer the question that actually matters for position-building:
   - *Reaction study*: after a >=2 std-dev commodity move, does the stock
     move in the expected direction over the next 5 days?
   - *Trend-continuation study*: after the commodity has been in a
     confirmed, low-drawdown uptrend for weeks (detected only after the
     fact, modeling a late entrant who missed the actual start), what does
     the stock do over the next 30/60/90 days -- measured as **excess
     return over the Nifty**, not raw return, for the same reason as step 1.

A pair only goes in `validated_pairs.json` once it holds up across these
checks, tagged `"tier": "validated"`. A pair with a fundamentally coherent
story but correlation that hasn't cleared significance yet is tagged
`"tier": "promising"` and included with that caveat visible in the output.

## Current validated universe

| Commodity | Validated | Promising | Notes |
|---|---|---|---|
| Brent Crude | OIL.NS, ONGC.NS (+), HPCL/BPCL.NS (-), ASIANPAINT.NS (-), INDIGO.NS (mixed) | IOC.NS, PIDILITIND.NS (-) | Cleanest result -- signs match business logic almost exactly. OMCs behave like *consumers* (negative), not producers, due to India's regulated retail pricing / under-recovery dynamic. IOC was validated at n=8 candidates, dropped to promising once FDR correction tightened at n=17. |
| Copper | POLYCAB.NS, KEI.NS, APARINDS.NS (+) | HAVELLS.NS (+) | Signal lives in trend-continuation, not day-to-day correlation -- these are demand-cycle co-movers, not simple cost-passthrough. |
| Silver | HINDZINC.NS (+) | -- | Strongest correlation found (r=0.51), though FDR significance is now marginal (p_adj=0.063) after testing against a larger candidate batch -- kept validated on overall strength of evidence. |
| Gold | -- | MUTHOOTFIN.NS, MANAPPURAM.NS (+) vs KALYANKJIL.NS (-) | Not yet statistically significant. Expanding candidates revealed jewellers aren't a uniform category -- Thangamayil and Senco Gold show *positive* trend-continuation, contradicting Kalyan Jewellers' negative pattern. Treat the jeweller-side story as unresolved. |

**Explicitly not included** (tested, no validated pair found -- see
`validated_pairs.json`'s `_not_included` section for the reasoning):
Sugar (global ICE benchmark is the wrong proxy for India's policy-driven
sugar economics), Aluminium, Iron ore (needs a China-demand-linked or
domestic price series instead of the thin Singapore contract used here).

## Repo layout

```
correlation_engine.py    the backtest engine (correlation, reaction, trend-continuation)
validated_pairs.json     curated output of the backtest -- what daily_scan.py reads
daily_scan.py             daily entrypoint: checks today's data, writes data/<date>.json
build_chart_data.py       generates docs/chart_data.json (indexed price series + historical
                           trend-confirmation instances per pair) -- run by hand after
                           validated_pairs.json changes, not part of the daily job
build_site.py             renders data/*.json + chart_data.json into docs/index.html
site_template.html        the HTML/CSS shell build_site.py fills in
data/                     one JSON file per day the scan has run (generated)
docs/                     generated static site, served by GitHub Pages
.github/workflows/daily.yml   the scheduled job (scan -> build site -> commit both)
requirements.txt
```

After changing validated_pairs.json (adding/removing a pair, or changing a
`trend_direction` override), regenerate the charts before rebuilding the site:

```bash
python3 build_chart_data.py && python3 build_site.py
```

## Running manually

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 daily_scan.py
```

To test/validate a new commodity or candidate stock, use
`correlation_engine.analyze_commodity(commodity_ticker, stock_tickers,
market_ticker="^NSEI")` directly -- see the git history for example
invocations against sugar, copper, oil, silver, gold, aluminium, and iron ore.

## Known limitations

- Small sample sizes throughout: trend-confirmation events are ~10-18 per
  commodity over the 2018-2026 backtest window, and they're not fully
  independent of each other (they cluster within the same underlying
  commodity supercycles). Treat hit-rates and medians as directional, not
  precise.
- `yfinance` is unofficial (scrapes Yahoo Finance) -- no SLA, could break.
- The commodity benchmark has to be the right proxy for the equity side;
  global futures prices work well for internationally-priced commodities
  (oil, copper, silver) but not for ones dominated by domestic policy
  (sugar) or a different demand driver than the traded contract reflects
  (iron ore, arguably needs China demand rather than the Singapore contract).
