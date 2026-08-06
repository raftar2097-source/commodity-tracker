"""
Commodity -> Stock correlation engine.

Two independent modules, per the design discussion:
  1. Reaction study      - commodity has a big move TODAY, does a candidate
                            stock move (in the expected direction) over the
                            next few days?
  2. Trend-continuation  - commodity has been in a CONFIRMED, sustained
                            uptrend for weeks. Even entering late (at
                            confirmation, not at the true start), how much
                            of the subsequent move does the stock capture
                            over the following 1-3 months?

Both are run on market-beta-stripped ("idiosyncratic") returns, so a stock
that's merely correlated with the S&P (not with the commodity specifically)
gets filtered out rather than falsely flagged.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests

# ----------------------------------------------------------------------
# 1. Data
# ----------------------------------------------------------------------

def fetch_prices(tickers, start, end=None):
    """Adjusted close prices for a list of tickers, one column each."""
    raw = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)["Close"]
    if isinstance(raw, pd.Series):
        raw = raw.to_frame(tickers[0])
    return raw.dropna(how="all")


def log_returns(price_df):
    return np.log(price_df / price_df.shift(1)).dropna(how="all")


def load_domestic_sugar_price(csv_path="data_sources/chinimandi_retail_sugar_prices.csv"):
    """Daily domestic retail sugar price (M-30, GST-inclusive), averaged
    across 9 Indian cities (Delhi, Kanpur, Raipur, Mumbai, Ranchi, Kolkata,
    Guwahati, Hyderabad, Chennai). Source: chinimandi.com/retail-prices,
    pulled 2026-08-06 via the page's own DataTable (no public API; the
    page renders the full 1,237-row history client-side, retrieved by
    driving the DataTable's JS to load all rows then exporting a CSV).
    Covers 2022-04-05 onward -- ~4.3 years, shorter than the 8-year window
    used for other commodities, but a real domestic (not global-benchmark)
    price series, which is what sugar specifically needed."""
    df = pd.read_csv(csv_path)
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    city_cols = [c for c in df.columns if c != "Date"]
    for c in city_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")  # "NR" (not reported) -> NaN
    df["avg_price"] = df[city_cols].mean(axis=1, skipna=True)
    series = df.set_index("Date")["avg_price"].sort_index()
    return series


def load_domestic_sugar_wholesale_price(csv_path="data_sources/chinimandi_wholesale_sugar_prices.csv"):
    """Daily domestic wholesale/ex-mill sugar price (M-30, GST-inclusive,
    per quintal), averaged across the same 9 cities as the retail series.
    Same source and extraction method as load_domestic_sugar_price(), but
    covers 2021-07-09 onward (~5 years) and is far more volatile -- retail
    prices are administratively smoothed (buffer stock policy, MSP-driven),
    wholesale/ex-mill prices are closer to a real market price. Source data
    has ~2.9x duplicate rows per date (exact repeats, a publishing artifact
    on chinimandi's end, not a multi-session quote), inconsistent date
    zero-padding (e.g. '31/1/2026' vs '06/08/2026'), and at least one
    repeated header row embedded mid-file (the source data appears to be
    two backend date-range chunks concatenated, each with its own header)
    Also has scattered malformed date strings (e.g. a missing '/' separator)
    that no single strptime format handles -- parsed with errors='coerce'
    and dropped rather than patched one-by-one, since new malformed rows
    could appear in any future re-pull."""
    df = pd.read_csv(csv_path)
    df = df[df["Date"] != "Date"]
    parsed_dates = pd.to_datetime(df["Date"], format="mixed", dayfirst=True, errors="coerce")
    n_bad = parsed_dates.isna().sum()
    if n_bad:
        print(f"load_domestic_sugar_wholesale_price: dropping {n_bad} rows with unparseable dates")
    df = df.assign(Date=parsed_dates).dropna(subset=["Date"])
    df = df.drop_duplicates()
    city_cols = [c for c in df.columns if c != "Date"]
    for c in city_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")  # "NR" (not reported) -> NaN
    df["avg_price"] = df[city_cols].mean(axis=1, skipna=True)
    series = df.groupby("Date")["avg_price"].mean().sort_index()
    return series


# ----------------------------------------------------------------------
# 2. Market-beta stripping
# ----------------------------------------------------------------------

def strip_market_beta(returns: pd.Series, market_returns: pd.Series) -> pd.Series:
    """Regress `returns` on `market_returns`; return the residual series
    (the part of the move NOT explained by the broad market)."""
    aligned = pd.concat([returns, market_returns], axis=1, join="inner").dropna()
    aligned.columns = ["y", "mkt"]
    if len(aligned) < 30:
        raise ValueError("not enough overlapping data to strip market beta")
    slope, intercept, r, p, se = stats.linregress(aligned["mkt"], aligned["y"])
    resid = aligned["y"] - (intercept + slope * aligned["mkt"])
    return resid


# ----------------------------------------------------------------------
# 3. Multi-window stability + significance
# ----------------------------------------------------------------------

def multi_window_correlation(commodity_resid: pd.Series, stock_resid: pd.Series,
                              windows=(30, 60, 90, 180)):
    """Correlate idiosyncratic returns over several trailing windows ending
    at the same (most recent) date, to check the relationship isn't an
    artifact of one particular lookback length."""
    aligned = pd.concat([commodity_resid, stock_resid], axis=1, join="inner").dropna()
    aligned.columns = ["commodity", "stock"]
    results = {}
    for w in windows:
        if len(aligned) < w:
            continue
        window_df = aligned.iloc[-w:]
        r, p = stats.pearsonr(window_df["commodity"], window_df["stock"])
        results[w] = {"r": r, "p": p, "n": w}
    return results


def stability_summary(window_results: dict):
    if not window_results:
        return {"mean_r": np.nan, "min_r": np.nan, "sign_consistent": False, "max_p": np.nan}
    rs = [v["r"] for v in window_results.values()]
    ps = [v["p"] for v in window_results.values()]
    signs = set(np.sign(rs))
    return {
        "mean_r": float(np.mean(rs)),
        "min_r": float(np.min(rs)) if np.mean(rs) >= 0 else float(np.max(rs)),
        "sign_consistent": len(signs) == 1,
        "max_p": float(np.max(ps)),
    }


def fdr_filter(pair_stats: dict, alpha=0.05):
    """Benjamini-Hochberg correction across all tested pairs, so that
    testing many candidate stocks doesn't generate false positives just
    from the number of tests run."""
    tickers = list(pair_stats.keys())
    pvals = [pair_stats[t]["max_p"] for t in tickers]
    reject, pvals_corrected, *_ = multipletests(pvals, alpha=alpha, method="fdr_bh")
    for t, sig, p_adj in zip(tickers, reject, pvals_corrected):
        pair_stats[t]["fdr_significant"] = bool(sig)
        pair_stats[t]["p_adj"] = float(p_adj)
    return pair_stats


# ----------------------------------------------------------------------
# 4. Reaction study (short-horizon: commodity spikes -> stock reacts)
# ----------------------------------------------------------------------

def reaction_study(commodity_returns: pd.Series, stock_returns: pd.Series,
                    z_thresh=2.0, vol_window=60, forward_days=5):
    aligned = pd.concat([commodity_returns, stock_returns], axis=1, join="inner").dropna()
    aligned.columns = ["commodity", "stock"]

    roll_std = aligned["commodity"].rolling(vol_window).std()
    z = aligned["commodity"] / roll_std
    event_dates = aligned.index[(z.abs() >= z_thresh) & roll_std.notna()]

    events = []
    for d in event_dates:
        loc = aligned.index.get_loc(d)
        if loc + forward_days >= len(aligned):
            continue
        commodity_move = aligned["commodity"].iloc[loc]
        fwd_stock_return = aligned["stock"].iloc[loc + 1: loc + 1 + forward_days].sum()
        expected_sign = np.sign(commodity_move)
        events.append({
            "date": d.date().isoformat(),
            "commodity_move_pct": round(float(commodity_move) * 100, 2),
            "stock_fwd_return_pct": round(float(fwd_stock_return) * 100, 2),
            "direction_match": bool(np.sign(fwd_stock_return) == expected_sign),
        })

    if not events:
        return {"n_events": 0, "hit_rate": np.nan, "avg_fwd_return_pct": np.nan, "events": []}

    hit_rate = np.mean([e["direction_match"] for e in events])
    avg_fwd = np.mean([e["stock_fwd_return_pct"] for e in events])
    return {"n_events": len(events), "hit_rate": round(float(hit_rate), 2),
            "avg_fwd_return_pct": round(float(avg_fwd), 2), "events": events}


# ----------------------------------------------------------------------
# 5. Trend-continuation study (medium-horizon: confirmed trend -> late entry)
# ----------------------------------------------------------------------

def detect_trend_confirmations(commodity_price: pd.Series, trend_window=60,
                                min_return=0.10, max_drawdown=0.05, persist_days=10):
    """A trend is 'confirmed' on the first day that:
       - trailing `trend_window`-day cumulative return >= min_return, AND
       - max pullback from the running peak within that window <= max_drawdown
       and that condition then holds for `persist_days` consecutive days
       (so we don't confirm on a single lucky day)."""
    price = commodity_price.dropna()
    cum_return = price / price.shift(trend_window) - 1

    roll_max = price.rolling(trend_window).max()
    drawdown = (roll_max - price) / roll_max

    qualifies = (cum_return >= min_return) & (drawdown <= max_drawdown)
    persistent = qualifies.rolling(persist_days).sum() == persist_days

    confirmations = []
    in_trend = False
    for d, ok in persistent.items():
        if ok and not in_trend:
            confirmations.append(d)
            in_trend = True
        elif not ok:
            in_trend = False
    return confirmations


def trend_continuation_study(commodity_price: pd.Series, stock_price: pd.Series,
                              market_price: pd.Series,
                              trend_window=60, min_return=0.10, max_drawdown=0.05,
                              persist_days=10, forward_horizons=(30, 60, 90),
                              late_capture_pct=0.15, expected_direction="positive"):
    """Forward returns are reported both raw AND as excess-over-market
    (stock forward return minus the market's forward return over the same
    horizon). Raw return answers 'did the stock go up'; excess return
    answers 'did the stock go up because of the commodity trend, or just
    because the whole market was rallying at the same time' -- the latter
    is the one that should drive the ranking, since a stock that merely
    tracks a broad bull market alongside the commodity isn't a real
    commodity-linked position.

    `expected_direction` controls what counts as 'reached_target': for a
    producer we expect to rise (excess_return >= +late_capture_pct); for a
    consumer we expect to fall on a commodity uptrend, so the target is
    excess_return <= -late_capture_pct instead. Getting this backwards
    silently mislabels every negative-direction pair's hits as misses and
    vice versa -- pass the pair's actual expected direction, don't rely on
    the 'positive' default outside of quick exploratory calls."""
    confirmations = detect_trend_confirmations(
        commodity_price, trend_window, min_return, max_drawdown, persist_days)

    stock = stock_price.dropna()
    market = market_price.dropna()
    results_by_horizon = {h: [] for h in forward_horizons}

    for d in confirmations:
        if d not in stock.index:
            idx = stock.index.searchsorted(d)
            if idx >= len(stock.index):
                continue
            d_eff = stock.index[idx]
            if (d_eff - d).days > 15:
                # d predates this stock's listing (or a long trading halt) by
                # more than a routine holiday gap -- using the earliest
                # available price as a stand-in would fabricate a signal for
                # a confirmation date the stock didn't exist for, rather than
                # measuring one. Skip it instead.
                continue
        else:
            d_eff = d
        loc = stock.index.get_loc(d_eff)
        entry_price = stock.iloc[loc]

        m_loc = market.index.searchsorted(d_eff)
        if m_loc >= len(market):
            continue
        m_entry_price = market.iloc[m_loc]

        for h in forward_horizons:
            if loc + h >= len(stock) or m_loc + h >= len(market):
                continue
            fwd_price = stock.iloc[loc + h]
            fwd_return = fwd_price / entry_price - 1

            m_fwd_price = market.iloc[m_loc + h]
            m_fwd_return = m_fwd_price / m_entry_price - 1

            excess_return = fwd_return - m_fwd_return
            if expected_direction == "positive":
                reached_target = excess_return >= late_capture_pct
            else:
                reached_target = excess_return <= -late_capture_pct
            results_by_horizon[h].append({
                "confirmation_date": d.date().isoformat(),
                "forward_return_pct": round(float(fwd_return) * 100, 2),
                "market_return_pct": round(float(m_fwd_return) * 100, 2),
                "excess_return_pct": round(float(excess_return) * 100, 2),
                "reached_target": bool(reached_target),
            })

    summary = {}
    for h, rows in results_by_horizon.items():
        if not rows:
            summary[h] = {"n": 0}
            continue
        raw = [r["forward_return_pct"] for r in rows]
        excess = [r["excess_return_pct"] for r in rows]
        summary[h] = {
            "n": len(rows),
            "median_return_pct": round(float(np.median(raw)), 2),
            "mean_return_pct": round(float(np.mean(raw)), 2),
            "worst_return_pct": round(float(np.min(raw)), 2),
            "median_excess_pct": round(float(np.median(excess)), 2),
            "mean_excess_pct": round(float(np.mean(excess)), 2),
            "worst_excess_pct": round(float(np.min(excess)), 2),
            "pct_hitting_target": round(float(np.mean([r["reached_target"] for r in rows])), 2),
            "instances": rows,
        }
    return {"n_confirmations": len(confirmations), "by_horizon": summary}


# ----------------------------------------------------------------------
# 6. Orchestration
# ----------------------------------------------------------------------

def analyze_commodity(commodity_ticker, stock_tickers, market_ticker="SPY",
                       start="2018-01-01", commodity_price=None):
    """commodity_price: optional pre-built pd.Series (DatetimeIndex -> price)
    for commodities with no tradeable futures ticker -- e.g. a domestic
    price series scraped/loaded from a non-yfinance source. When given,
    commodity_ticker is used only as a label; stock/market prices are still
    fetched normally and aligned against the supplied series via the same
    inner-join logic every sub-function already uses."""
    stock_prices = fetch_prices(stock_tickers + [market_ticker], start=start)
    stock_returns = log_returns(stock_prices)
    market_r = stock_returns[market_ticker]

    if commodity_price is not None:
        commodity_price_full = commodity_price[commodity_price.index >= pd.Timestamp(start)]
        commodity_r = log_returns(commodity_price_full.to_frame("c"))["c"]
    else:
        commodity_price_full = fetch_prices([commodity_ticker], start=start)[commodity_ticker]
        commodity_r = stock_returns[commodity_ticker] if commodity_ticker in stock_returns.columns \
            else log_returns(commodity_price_full.to_frame("c"))["c"]

    commodity_resid = strip_market_beta(commodity_r, market_r)

    pair_stats = {}
    reaction_results = {}
    trend_results = {}

    for stock in stock_tickers:
        stock_r = stock_returns[stock]
        stock_resid = strip_market_beta(stock_r, market_r)

        window_corrs = multi_window_correlation(commodity_resid, stock_resid)
        stab = stability_summary(window_corrs)
        pair_stats[stock] = stab

        reaction_results[stock] = reaction_study(commodity_r, stock_r)
        trend_results[stock] = trend_continuation_study(
            commodity_price_full, stock_prices[stock], stock_prices[market_ticker])

    pair_stats = fdr_filter(pair_stats)

    return {
        "correlation": pair_stats,
        "reaction": reaction_results,
        "trend": trend_results,
    }


# ----------------------------------------------------------------------
# 7. Live status (for the daily scan, as opposed to the historical backtest)
# ----------------------------------------------------------------------

def current_status(commodity_price: pd.Series, vol_window=60, z_thresh=2.0,
                    trend_window=60, min_return=0.10, max_drawdown=0.05,
                    persist_days=10):
    """Where does the commodity stand as of the most recent close: was
    today a reaction-study 'event' (big move), and are we currently inside
    a confirmed trend-continuation regime? Uses the same thresholds as the
    backtest so today's flags mean the same thing the historical stats do."""
    price = commodity_price.dropna()
    returns = np.log(price / price.shift(1)).dropna()

    roll_std = returns.rolling(vol_window).std()
    latest_return = returns.iloc[-1]
    latest_std = roll_std.iloc[-1]
    latest_z = latest_return / latest_std if pd.notna(latest_std) and latest_std > 0 else np.nan

    cum_return = price / price.shift(trend_window) - 1
    roll_max = price.rolling(trend_window).max()
    drawdown = (roll_max - price) / roll_max
    qualifies = (cum_return >= min_return) & (drawdown <= max_drawdown)
    persistent = qualifies.rolling(persist_days).sum() == persist_days

    return {
        "date": price.index[-1].date().isoformat(),
        "latest_price": float(price.iloc[-1]),
        "latest_return_pct": round(float(latest_return) * 100, 2),
        "z_score": round(float(latest_z), 2) if pd.notna(latest_z) else None,
        "event_today": bool(abs(latest_z) >= z_thresh) if pd.notna(latest_z) else False,
        "trend_cum_return_pct": round(float(cum_return.iloc[-1]) * 100, 2) if pd.notna(cum_return.iloc[-1]) else None,
        "trend_drawdown_pct": round(float(drawdown.iloc[-1]) * 100, 2) if pd.notna(drawdown.iloc[-1]) else None,
        "in_confirmed_trend": bool(persistent.iloc[-1]) if pd.notna(persistent.iloc[-1]) else False,
    }


if __name__ == "__main__":
    SUGAR_TICKER = "SB=F"
    CANDIDATE_STOCKS = ["ADM", "BG", "KO", "PEP", "HSY", "MDLZ", "TATE.L"]

    results = analyze_commodity(SUGAR_TICKER, CANDIDATE_STOCKS)

    print("\n=== Idiosyncratic correlation (market-beta stripped), multi-window stability, FDR-adjusted ===")
    rows = []
    for stock, stat in results["correlation"].items():
        rows.append({
            "stock": stock,
            "mean_r": stat["mean_r"],
            "min_r": stat["min_r"],
            "sign_consistent": stat["sign_consistent"],
            "p_adj": stat["p_adj"],
            "fdr_significant": stat["fdr_significant"],
        })
    corr_df = pd.DataFrame(rows).sort_values("mean_r", key=abs, ascending=False)
    print(corr_df.to_string(index=False))

    print("\n=== Reaction study (5-day forward return after a >=2 std-dev sugar move) ===")
    for stock, r in results["reaction"].items():
        print(f"{stock}: n_events={r['n_events']} hit_rate={r['hit_rate']} avg_fwd_return_pct={r['avg_fwd_return_pct']}")

    print("\n=== Trend-continuation study (late entry at trend confirmation, forward return) ===")
    for stock, r in results["trend"].items():
        print(f"\n{stock}: {r['n_confirmations']} trend confirmations detected")
        for h, s in r["by_horizon"].items():
            if s["n"] == 0:
                print(f"  {h}d horizon: no data")
                continue
            print(f"  {h}d horizon: n={s['n']} raw_median={s['median_return_pct']}% "
                  f"excess_median={s['median_excess_pct']}% excess_worst={s['worst_excess_pct']}% "
                  f"%>=15%_excess_target={s['pct_hitting_target']}")
