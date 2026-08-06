"""
Generates docs/chart_data.json: for every pair in validated_pairs.json, an
indexed (rebased to 100) commodity-vs-stock price series plus the exact
historical trend-confirmation instances (date, 90d excess return, hit/miss)
that back that pair's backtest stats.

Run by hand after validated_pairs.json changes -- not part of the daily job,
since the underlying history barely moves day to day.
"""
import json
from pathlib import Path

import pandas as pd

from correlation_engine import fetch_prices, trend_continuation_study

CONFIG_PATH = Path(__file__).parent / "validated_pairs.json"
OUT_PATH = Path(__file__).parent / "docs" / "chart_data.json"
START = "2018-01-01"
MAX_POINTS = 420  # downsample target for the plotted line, instances stay exact


def downsample(dates, values, max_points):
    step = max(1, len(values) // max_points)
    d_ds, v_ds = dates[::step], values[::step]
    if d_ds[-1] != dates[-1]:
        d_ds.append(dates[-1])
        v_ds.append(values[-1])
    return d_ds, v_ds


def build_pair_chart(commodity_ticker, commodity_name, stock_ticker, stock_name,
                      market_ticker, prices, trend_direction="positive"):
    commodity_price = prices[commodity_ticker].dropna()
    stock_price = prices[stock_ticker].dropna()
    market_price = prices[market_ticker].dropna()

    aligned = pd.concat([commodity_price, stock_price], axis=1, join="inner").dropna()
    aligned.columns = ["commodity", "stock"]

    commodity_indexed = (aligned["commodity"] / aligned["commodity"].iloc[0] * 100).round(2)
    stock_indexed = (aligned["stock"] / aligned["stock"].iloc[0] * 100).round(2)

    dates = [d.date().isoformat() for d in aligned.index]
    d_ds, commodity_ds = downsample(dates, commodity_indexed.tolist(), MAX_POINTS)
    _, stock_ds = downsample(dates, stock_indexed.tolist(), MAX_POINTS)

    trend = trend_continuation_study(commodity_price, stock_price, market_price,
                                      expected_direction=trend_direction)
    instances_90d = trend["by_horizon"].get(90, {}).get("instances", [])
    instances = [
        {"date": i["confirmation_date"], "excess_pct": i["excess_return_pct"], "hit": i["reached_target"]}
        for i in instances_90d
    ]

    return {
        "commodity_ticker": commodity_ticker,
        "commodity_name": commodity_name,
        "stock_ticker": stock_ticker,
        "stock_name": stock_name,
        "dates": d_ds,
        "commodity_indexed": commodity_ds,
        "stock_indexed": stock_ds,
        "instances": instances,
    }


def main():
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    config.pop("_not_included", None)

    all_tickers = set()
    for spec in config.values():
        all_tickers.add(spec["market"])
        for pair in spec["pairs"]:
            all_tickers.add(pair["ticker"])
    for commodity_ticker in config:
        all_tickers.add(commodity_ticker)

    print(f"Fetching prices for {len(all_tickers)} tickers since {START}...")
    prices = fetch_prices(sorted(all_tickers), start=START)

    chart_data = {}
    for commodity_ticker, spec in config.items():
        for pair in spec["pairs"]:
            key = pair["ticker"]
            # trend_direction overrides expected_direction when a pair's
            # trend-continuation behavior diverges from its overall
            # (often reaction-study-based) expected direction -- e.g. IndiGo
            # reacts negatively same-day but trends positively over 90d.
            trend_direction = pair.get(
                "trend_direction",
                "positive" if "positive" in pair["expected_direction"] else "negative")
            print(f"  building chart for {key} vs {commodity_ticker} (trend_direction={trend_direction})...")
            try:
                chart_data[key] = build_pair_chart(
                    commodity_ticker, spec["name"], pair["ticker"], pair["name"],
                    spec["market"], prices, trend_direction=trend_direction)
            except Exception as e:
                print(f"  SKIPPED {key}: {e}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(chart_data, f, separators=(",", ":"))

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({len(chart_data)} pairs, {size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
