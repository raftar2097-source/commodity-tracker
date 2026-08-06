# Candidate queue

Living tracker for commodity/candidate research. Update this whenever a
new commodity gets tested, per the procedure in `CLAUDE.md`. Full
reasoning for every rejected commodity lives in `validated_pairs.json`'s
`_not_included` section -- this file is the short-form index into that.

## Live in validated_pairs.json

| Commodity | Status | Best pair(s) |
|---|---|---|
| Brent Crude (`BZ=F`) | validated | OIL.NS, ONGC.NS (+), HPCL/BPCL.NS (-), ASIANPAINT.NS (-) |
| Copper (`HG=F`) | validated | POLYCAB.NS, KEI.NS, APARINDS.NS (+) |
| Silver (`SI=F`) | validated | HINDZINC.NS (+) |
| Gold (`GC=F`) | promising | MUTHOOTFIN.NS, MANAPPURAM.NS (+) vs KALYANKJIL.NS (-) |
| Domestic Sugar wholesale (`DOMESTIC_SUGAR_WHOLESALE`, chinimandi.com) | promising | TRIVENI.NS (best, r=0.248), 5 others positive/sign-consistent |

## Tested, rejected

| Commodity | Why | Revisit if... |
|---|---|---|
| Aluminium (`ALI=F`) | No FDR-significant candidate; one attractive trend number (NATIONALUM.NS) had no correlation backing | A better candidate list turns up (only tested HINDALCO/NATIONALUM/VEDL) |
| Iron ore (`TIO=F`) | Thin Singapore contract, and India is iron-ore self-sufficient (producer/exporter) so domestic steel stocks may not track it | Try coking coal instead (see below) -- India *is* import-dependent for that specifically |
| Natural gas (`NG=F`, Henry Hub) | Wrong benchmark -- US domestic price, not what India's LNG imports (Asian spot/JKM) track. Tested Petronet, GAIL, IGL, MGL, Adani Total Gas | A free JKM/Asian LNG spot data source turns up |
| Palm oil (`CPO=F`) | Genuine benchmark, still no signal. Plausibly India's variable import duty adjustments smooth the pass-through | Unlikely to change without a policy shift; low priority to retry |
| Domestic sugar *retail* (chinimandi.com retail-prices) | Administratively smoothed -- only 1 usable trend-continuation event in 4.3 years even after recalibrating volatility threshold | Not planned -- wholesale (above) is the useful series |

## Ideas not yet tested

- **Platinum/palladium (PGM)** -- India imports ~100% of its PGM supply
  (auto catalytic converters, jewellery). High import dependence, but the
  equity universe is narrower/less obvious than oil or copper -- would
  need real research into which Indian auto-component or jewellery names
  are majorly PGM-exposed before backtesting, not just guessed.
- **Coking coal** -- distinct from iron ore (which failed): India imports
  a large share of coking/steel-grade coal specifically, since domestic
  coal is mostly thermal-grade. Same steel candidates (Tata Steel, JSW
  Steel, SAIL) but the properly import-dependent commodity leg. Need to
  find a usable global coking coal futures/price series first (not yet
  checked for yfinance availability).
- **Nickel** -- EV battery / stainless steel theme, India has minimal
  domestic nickel production so plausibly import-dependent, but not yet
  researched for either a data source or majorly-exposed Indian
  candidates.

## Explicitly ruled out (don't retry without new information)

- **Cotton** -- India is a net cotton *exporter*, wrong side of the
  import-dependence filter.
- **Wheat / rice** -- domestically procured under MSP/FCI, same
  domestic-policy problem as sugar, no reason to expect a cleaner result.
