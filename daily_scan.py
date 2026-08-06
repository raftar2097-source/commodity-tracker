"""
Daily scan entrypoint.

Reads validated_pairs.json (the output of the backtesting work in
correlation_engine.py -- recomputed periodically, not on every run) and
checks, for each tracked commodity, whether TODAY is:
  - a reaction-study 'event' (a big move that historically preceded a
    short-horizon stock reaction), and/or
  - inside a confirmed trend-continuation regime (the sustained-uptrend
    condition that historically preceded a captureable 1-3 month move,
    even for a late entrant).

Only commodities with an active flag produce output -- a quiet day means
no section printed, so the daily report stays short on non-event days.
"""

import json
from pathlib import Path
from datetime import date

import pandas as pd

from correlation_engine import fetch_prices, current_status, load_domestic_sugar_wholesale_price

CONFIG_PATH = Path(__file__).parent / "validated_pairs.json"
DATA_DIR = Path(__file__).parent / "data"

# Commodities with no yfinance ticker -- current_status() needs an actual
# price series for these, loaded via a custom source instead of fetch_prices().
CUSTOM_PRICE_LOADERS = {
    "DOMESTIC_SUGAR_WHOLESALE": load_domestic_sugar_wholesale_price,
}


def load_config():
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    config.pop("_not_included", None)
    return config


def refresh_custom_sources(config):
    if "DOMESTIC_SUGAR_WHOLESALE" in config:
        import scrape_domestic_sugar
        scrape_domestic_sugar.main()


def run_scan(lookback_days=400):
    config = load_config()
    refresh_custom_sources(config)
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    report = {"run_date": date.today().isoformat(), "commodities": {}}

    for commodity_ticker, spec in config.items():
        if commodity_ticker in CUSTOM_PRICE_LOADERS:
            commodity_price = CUSTOM_PRICE_LOADERS[commodity_ticker]()
        else:
            commodity_price = fetch_prices([commodity_ticker], start=start)[commodity_ticker]
        status = current_status(commodity_price)

        entry = {"name": spec["name"], "status": status, "signals": []}

        if status["event_today"] or status["in_confirmed_trend"]:
            for pair in spec["pairs"]:
                entry["signals"].append({
                    "ticker": pair["ticker"],
                    "name": pair["name"],
                    "role": pair["role"],
                    "expected_direction": pair["expected_direction"],
                    "tier": pair["tier"],
                    "backtest": pair["backtest"],
                    "triggered_by": [
                        t for t, flag in
                        [("reaction_event", status["event_today"]),
                         ("trend_continuation", status["in_confirmed_trend"])]
                        if flag
                    ],
                })

        report["commodities"][commodity_ticker] = entry

    return report


def print_report(report):
    print(f"=== Commodity daily scan: {report['run_date']} ===\n")
    any_signal = False

    for ticker, entry in report["commodities"].items():
        s = entry["status"]
        flags = []
        if s["event_today"]:
            flags.append(f"REACTION EVENT (z={s['z_score']})")
        if s["in_confirmed_trend"]:
            flags.append(f"IN CONFIRMED TREND (cum {s['trend_cum_return_pct']}% / {60}d)")

        if not flags:
            print(f"{entry['name']} ({ticker}): quiet -- price {s['latest_price']}, "
                  f"{s['latest_return_pct']}% today. No active signal.")
            continue

        any_signal = True
        print(f"{entry['name']} ({ticker}): {' | '.join(flags)}")
        print(f"  price {s['latest_price']}, {s['latest_return_pct']}% today, "
              f"date {s['date']}")
        for sig in entry["signals"]:
            bt = sig["backtest"]
            bt_str = ", ".join(f"{k}={v}" for k, v in bt.items() if k != "note")
            print(f"  -> {sig['name']} ({sig['ticker']}) [{sig['role']}] "
                  f"expected: {sig['expected_direction']} [{sig['tier']}]")
            print(f"     backtest: {bt_str}")
            if "note" in bt:
                print(f"     note: {bt['note']}")
        print()

    if not any_signal:
        print("\nNo active signals today across the tracked universe.")


def save_report(report):
    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / f"{report['run_date']}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    return out_path


if __name__ == "__main__":
    report = run_scan()
    print_report(report)
    out_path = save_report(report)
    print(f"\nSaved to {out_path}")
