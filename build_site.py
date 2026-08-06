"""
Regenerates docs/index.html (served by GitHub Pages) from data/*.json scan
results. Pure stdlib, no dependencies, run after every daily_scan.py run.
"""
import glob
import html
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")


def load_reports():
    files = sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))
    reports = []
    for f in files:
        with open(f) as fh:
            reports.append(json.load(fh))
    reports.sort(key=lambda r: r["run_date"], reverse=True)
    return reports


def direction_class(direction):
    if "positive" in direction:
        return "pos"
    if "negative" in direction:
        return "neg"
    return "mixed"


def render_signal(sig):
    bt = sig["backtest"]
    bt_bits = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in bt.items() if k != "note")
    note_html = f'<div class="sig-note">{html.escape(bt["note"])}</div>' if "note" in bt else ""
    dir_cls = direction_class(sig["expected_direction"])
    tier_cls = "promising" if sig["tier"] == "promising" else "validated"
    return f"""
      <div class="signal">
        <div class="signal-head">
          <span class="signal-name">{html.escape(sig['name'])}</span>
          <span class="signal-ticker">{html.escape(sig['ticker'])}</span>
          <span class="dir-chip {dir_cls}">{html.escape(sig['expected_direction'].replace('_', ' '))}</span>
          <span class="tier-chip {tier_cls}">{html.escape(sig['tier'].replace('_', ' '))}</span>
        </div>
        <div class="signal-role">{html.escape(sig['role'])}</div>
        <div class="signal-backtest">{html.escape(bt_bits)}</div>
        {note_html}
      </div>"""


def render_commodity(ticker, entry):
    s = entry["status"]
    flags = []
    if s["event_today"]:
        flags.append(("event", f"Reaction event (z={s['z_score']})"))
    if s["in_confirmed_trend"]:
        flags.append(("trend", f"Confirmed trend ({s['trend_cum_return_pct']}% cum.)"))

    status_cls = "active" if flags else "quiet"
    flag_html = "".join(
        f'<span class="flag-chip {cls}">{html.escape(label)}</span>' for cls, label in flags
    ) or '<span class="flag-chip quiet">quiet</span>'

    ret = s["latest_return_pct"]
    move_cls = "up" if ret > 0 else "down" if ret < 0 else ""
    move_sign = "+" if ret > 0 else ""
    signals_html = "".join(render_signal(sig) for sig in entry["signals"])

    return f"""
    <div class="commodity {status_cls}">
      <div class="commodity-head">
        <div class="commodity-title">
          <span class="commodity-name">{html.escape(entry['name'])}</span>
          <span class="commodity-ticker">{html.escape(ticker)}</span>
        </div>
        <div class="commodity-price">
          <span class="price">{s['latest_price']:.2f}</span>
          <span class="move {move_cls}">{move_sign}{ret}%</span>
        </div>
      </div>
      <div class="flags">{flag_html}</div>
      {f'<div class="signals">{signals_html}</div>' if signals_html else ''}
    </div>"""


def render_day(report, open_by_default=False):
    any_signal = any(e["signals"] for e in report["commodities"].values())
    badge = (
        '<span class="day-badge signal">signal</span>' if any_signal
        else '<span class="day-badge quiet">quiet</span>'
    )
    commodities_html = "".join(render_commodity(t, e) for t, e in report["commodities"].items())
    open_attr = " open" if (open_by_default or any_signal) else ""
    return f"""
    <details class="day {'signal-day' if any_signal else 'quiet-day'}"{open_attr}>
      <summary>
        <span class="day-date">{report['run_date']}</span>
        {badge}
      </summary>
      <div class="commodities-grid">{commodities_html}</div>
    </details>"""


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    reports = load_reports()

    total_days = len(reports)
    signal_days = sum(1 for r in reports if any(e["signals"] for e in r["commodities"].values()))
    commodities_tracked = len(reports[0]["commodities"]) if reports else 0

    if reports:
        latest_html = render_day(reports[0], open_by_default=True)
        history_html = "".join(render_day(r) for r in reports[1:]) or (
            '<p class="empty-state">No earlier history yet — check back tomorrow.</p>'
        )
    else:
        latest_html = '<p class="empty-state">No scans yet — check back after the next run.</p>'
        history_html = ""

    template_path = os.path.join(os.path.dirname(__file__), "site_template.html")
    with open(template_path) as f:
        template = f.read()

    output = (
        template
        .replace("{{DAYS_TRACKED}}", str(total_days))
        .replace("{{SIGNAL_DAYS}}", f"{signal_days} / {total_days}" if total_days else "—")
        .replace("{{COMMODITIES_TRACKED}}", str(commodities_tracked))
        .replace("{{LATEST}}", latest_html)
        .replace("{{HISTORY}}", history_html)
    )

    with open(os.path.join(DOCS_DIR, "index.html"), "w") as f:
        f.write(output)

    print(f"Built docs/index.html: {total_days} days tracked, {signal_days} with a signal.")


if __name__ == "__main__":
    main()
