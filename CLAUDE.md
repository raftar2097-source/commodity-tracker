# Commodity Tracker — project guide

See `README.md` for what this project is and how it's laid out. This file
is the process guide: how to add a new commodity or candidate stock
without silently degrading the thing that makes this project useful --
that every pair in `validated_pairs.json` has actually earned its place.

## Hard rule: no autonomous merges

Research, ticker-checking, and backtesting can run unattended (e.g. via
`/loop` or a scheduled agent) to do the legwork. **Adding or changing an
entry in `validated_pairs.json` always requires a human reviewing the
actual backtest output and approving it in conversation.** Never do this
as an unattended background step, no matter how clean a result looks.

Why this rule exists: every real bug and false lead caught in this
project so far was caught by skepticism and by actually looking at
rendered output, not by a checklist running on autopilot. See the red
flags below -- every one of them was a "the numbers looked fine" trap
that a purely mechanical pipeline would have sailed straight through.

## Adding a new commodity: the procedure

1. **Pick candidates with a real reason to expect a relationship**, not
   generic sector membership. The filter that's worked well: does India
   actually import this commodity at scale (so a global benchmark should
   pass through), or is it domestically produced/policy-controlled (in
   which case a global benchmark probably won't work -- see sugar)?
   Research which companies are *majorly* dependent on the commodity, not
   just tangentially exposed (a diversified conglomerate dilutes any real
   signal -- this happened repeatedly: Vedanta, Hindalco, Marico, Godrej
   Agrovet, IIFL all showed weaker results than their more-focused peers).
2. **Verify ticker/data availability before trusting anything downstream**
   -- a ticker resolving with `yf.download` isn't enough; check the row
   count and date range. yfinance's Indian-equity coverage has real gaps
   (see GSPL/Gujarat Gas below).
3. **Run the backtest**: `correlation_engine.analyze_commodity(commodity_ticker,
   stock_tickers, market_ticker="^NSEI", start="2018-01-01")` (or pass a
   pre-built `pd.Series` via `commodity_price=` for a non-yfinance source).
   Test the full candidate batch together so FDR correction is honest.
4. **Run every item in the red-flag checklist below** before deciding
   anything.
5. **Tier assignment**: `validated` needs FDR-significant correlation with
   consistent sign across all windows, or (for pairs like Polycab/KEI
   where correlation is weak but trend-continuation is strong and
   consistent after the same market-beta rigor) equivalent-strength
   evidence from the trend-continuation study instead. `promising` is a
   fundamentally coherent, correctly-signed story that hasn't cleared
   significance yet -- state why in a `note`, don't just omit the caveat.
6. **Update `validated_pairs.json`** -- new pairs, or add a `_not_included`
   entry with the actual reason if nothing validated. Be honest about
   null results; they're documented findings, not failures.
7. **Regenerate and verify visually**: `python3 build_chart_data.py &&
   python3 build_site.py`, then actually look at it in a browser (serve
   `docs/` locally) before pushing -- rendering bugs (see red flags) don't
   show up by reading the generated HTML.
8. **Commit and push**, with a commit message that states the actual
   finding, not just "add X".

## Red flags to check every time (all found the hard way this session)

- **Recently-listed stock?** Check whether historical trend-confirmation
  dates predate its IPO. `trend_continuation_study()` already skips a
  confirmation date if the nearest available price is >15 days later --
  but a new custom price loader or a different function might not.
- **Negative-direction pair?** Confirm `reached_target` is computed
  direction-aware (`excess_return <= -target` for a consumer/negative
  pair, not `>= +target`). This bug shipped once (silently mislabeled
  every OMC/consumer pair) before being caught by looking at the
  rendered track-record table.
- **A trend-continuation number looks unusually good?** Check its
  correlation backing and event count. A flashy median with no
  correlation support and a small n (Hindustan Copper pre-fix, Gokul
  Refoils, NATIONALUM, RRKABEL, Premier Energies) has been noise every
  single time it's happened so far.
- **Company recently merged, demerged, or restructured?** (e.g. the
  GSPC+GSPL+GEL amalgamation into Gujarat Gas, May 2026, which also spun
  off a new "GSPL Transmission Ltd"). Splicing pre/post-restructuring
  prices under the same ticker is the same class of error as the IPO
  bug, worse -- it's not a missing-history gap, it's a different
  business. Verify via search if a data gap coincides with unusually
  clean relisting dates.
- **Retail vs. wholesale/spot price** can behave completely differently
  for the same commodity (confirmed for sugar: retail is administratively
  smoothed and produced almost no usable trend-continuation events;
  wholesale moved like a real market price). Don't assume the first price
  series you find is representative.
- **Is the global benchmark actually the right proxy?** Henry Hub (`NG=F`)
  is a US domestic price, not what India's LNG imports track (Asian
  spot/JKM). ICE sugar futures don't reflect India's domestically-produced,
  policy-controlled sugar economics. A null result on a global benchmark
  doesn't mean "no relationship" -- check whether the benchmark itself
  is wrong before concluding that.
- **New CSS class names in the site**: check for collisions with existing
  classes before assuming a new `<span class="commodity">` etc. is scoped
  correctly. `.legend-swatch.commodity` silently inherited padding/border
  from the pre-existing `.commodity` card class and rendered as a giant
  square instead of a thin line-key. Prefer prefixed names
  (`chart-commodity`, not `commodity`) for anything chart-related.
- **A scraped/custom CSV data source**: check for embedded duplicate
  header rows, inconsistent date zero-padding, and malformed rows before
  trusting a single `pd.to_datetime(..., format=...)` call -- all three
  showed up in the chinimandi wholesale sugar data. Parse with
  `errors="coerce"` and drop/report bad rows rather than assuming clean
  input. Also check whether the file ends with a trailing newline before
  appending to it (a missing one silently corrupted the first
  automated sugar-scraper run).

## Candidate queue

See `QUEUE.md` for what's validated, what's been tested and rejected
(with reasons), and ideas not yet tried.
