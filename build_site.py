"""
Regenerates docs/index.html (served by GitHub Pages) from data/*.json scan
results. Pure stdlib, no dependencies, run after every daily_scan.py run.
"""
import glob
import html
import json
import os
from datetime import date

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DOCS_DIR = os.path.join(os.path.dirname(__file__), "docs")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "validated_pairs.json")
CHART_DATA_PATH = os.path.join(DOCS_DIR, "chart_data.json")


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


def load_config():
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    config.pop("_not_included", None)
    return config


def load_chart_data():
    if not os.path.exists(CHART_DATA_PATH):
        return {}
    with open(CHART_DATA_PATH) as f:
        return json.load(f)


def render_chart_svg(pair):
    """Small multiples: two stacked panels (commodity, stock) sharing a date
    axis, each auto-scaled to its OWN y-range rather than one shared axis.
    A commodity producer's stock typically moves far more than the
    commodity itself (operating leverage) -- e.g. Brent might be up 20%
    over 8 years while its linked producer is up 300%+. Forcing both onto
    one linear axis makes the commodity line look flat; a dual-axis chart
    (two y-scales on one plot) would fix the visual but make the lines'
    crossing points meaningless, which is worse. Two independently-scaled
    panels, aligned on the same x-axis, keep each series readable while
    still showing whether they move together in time -- the vertical
    marker lines spanning both panels are what carry that alignment."""
    dates = pair["dates"]
    commodity = pair["commodity_indexed"]
    stock = pair["stock_indexed"]
    n = len(dates)
    if n < 2:
        return '<p class="empty-state">Not enough data to chart.</p>'

    width = 640
    pad_left, pad_right = 8, 60
    panel_h, panel_gap = 84, 16
    label_h, bottom_pad = 16, 20
    plot_w = width - pad_left - pad_right
    top_panel_top = label_h
    bottom_panel_top = label_h + panel_h + panel_gap + label_h
    height = bottom_panel_top + panel_h + bottom_pad

    def x_at(i):
        return pad_left + (i / (n - 1)) * plot_w

    def make_y_scale(series, panel_top):
        v_min, v_max = min(series), max(series)
        v_range = (v_max - v_min) or 1
        v_pad = v_range * 0.1
        v_min -= v_pad
        v_max += v_pad

        def y_at(v):
            return panel_top + (1 - (v - v_min) / (v_max - v_min)) * panel_h
        return y_at

    y_commodity = make_y_scale(commodity, top_panel_top)
    y_stock = make_y_scale(stock, bottom_panel_top)

    def path_for(series, y_scale):
        return "M " + " L ".join(f"{x_at(i):.1f},{y_scale(v):.1f}" for i, v in enumerate(series))

    start_date = date.fromisoformat(dates[0])
    end_date = date.fromisoformat(dates[-1])
    span_days = (end_date - start_date).days or 1

    def x_for_date(d_str):
        d = date.fromisoformat(d_str)
        frac = min(max((d - start_date).days / span_days, 0), 1)
        return pad_left + frac * plot_w

    markers = []
    for inst in pair["instances"]:
        mx = x_for_date(inst["date"])
        idx = min(max(round((mx - pad_left) / plot_w * (n - 1)), 0), n - 1)
        cls = "hit" if inst["hit"] else "miss"
        sign = "+" if inst["excess_pct"] > 0 else ""
        title = (f"Trend confirmed {inst['date']}: 90d excess return {sign}{inst['excess_pct']}% "
                  f"({'hit' if inst['hit'] else 'missed'} the 15% target)")
        title_html = f"<title>{html.escape(title)}</title>"
        markers.append(
            f'<circle class="instance-marker {cls}" cx="{mx:.1f}" cy="{y_commodity(commodity[idx]):.1f}" r="5">{title_html}</circle>'
            f'<circle class="instance-marker {cls}" cx="{mx:.1f}" cy="{y_stock(stock[idx]):.1f}" r="5">{title_html}</circle>'
        )

    return f"""
    <svg class="track-chart" viewBox="0 0 {width} {height}" role="img"
         aria-label="{html.escape(pair['commodity_name'])} vs {html.escape(pair['stock_name'])}, each indexed to 100 at {dates[0]}, shown as separate panels">
      <text class="panel-label chart-commodity" x="{pad_left}" y="{top_panel_top - 5}">{html.escape(pair['commodity_name'])} (indexed)</text>
      <text class="panel-label chart-stock" x="{pad_left}" y="{bottom_panel_top - 5}">{html.escape(pair['stock_name'])} (indexed)</text>
      {''.join(f'<line class="instance-connector-bg" x1="{x_for_date(i["date"]):.1f}" y1="{top_panel_top:.1f}" x2="{x_for_date(i["date"]):.1f}" y2="{bottom_panel_top + panel_h:.1f}" />' for i in pair["instances"])}
      <line class="chart-baseline" x1="{pad_left}" y1="{y_commodity(100):.1f}" x2="{width - pad_right}" y2="{y_commodity(100):.1f}" />
      <line class="chart-baseline" x1="{pad_left}" y1="{y_stock(100):.1f}" x2="{width - pad_right}" y2="{y_stock(100):.1f}" />
      <path class="chart-line chart-commodity" d="{path_for(commodity, y_commodity)}" />
      <path class="chart-line chart-stock" d="{path_for(stock, y_stock)}" />
      {''.join(markers)}
      <text class="chart-end-label chart-commodity" x="{width - pad_right + 6}" y="{y_commodity(commodity[-1]) + 4:.1f}">{commodity[-1]:.0f}</text>
      <text class="chart-end-label chart-stock" x="{width - pad_right + 6}" y="{y_stock(stock[-1]) + 4:.1f}">{stock[-1]:.0f}</text>
      <text class="chart-date-label" x="{pad_left}" y="{height - 6}">{dates[0]}</text>
      <text class="chart-date-label end" x="{width - pad_right}" y="{height - 6}" text-anchor="end">{dates[-1]}</text>
    </svg>"""


def render_instances_table(instances):
    if not instances:
        return '<p class="empty-state">No confirmed trend instances in the backtest window.</p>'
    rows = []
    for inst in sorted(instances, key=lambda i: i["date"], reverse=True):
        cls = "hit" if inst["hit"] else "miss"
        symbol = "✓" if inst["hit"] else "✗"
        sign = "+" if inst["excess_pct"] > 0 else ""
        rows.append(
            f'<tr><td>{html.escape(inst["date"])}</td>'
            f'<td class="num">{sign}{inst["excess_pct"]}%</td>'
            f'<td class="instance-result {cls}">{symbol} {"hit" if inst["hit"] else "miss"}</td></tr>'
        )
    return f"""
    <table class="instances-table">
      <thead><tr><th>Trend confirmed</th><th>90d excess return</th><th>vs. 15% target</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>"""


def render_track_pair(pair_meta, chart_data):
    ticker = pair_meta["ticker"]
    cd = chart_data.get(ticker)
    if not cd:
        return ""
    dir_cls = direction_class(pair_meta["expected_direction"])
    tier_cls = "promising" if pair_meta["tier"] == "promising" else "validated"
    n_hit = sum(1 for i in cd["instances"] if i["hit"])
    n_total = len(cd["instances"])
    hit_summary = f"{n_hit}/{n_total} instances hit target" if n_total else "no instances in window"

    return f"""
    <details class="track-pair">
      <summary>
        <span class="signal-name">{html.escape(pair_meta['name'])}</span>
        <span class="signal-ticker">{html.escape(ticker)}</span>
        <span class="dir-chip {dir_cls}">{html.escape(pair_meta['expected_direction'].replace('_', ' '))}</span>
        <span class="tier-chip {tier_cls}">{html.escape(pair_meta['tier'].replace('_', ' '))}</span>
        <span class="track-hit-summary">{hit_summary}</span>
      </summary>
      <div class="track-body">
        {render_chart_svg(cd)}
        {render_instances_table(cd['instances'])}
      </div>
    </details>"""


def render_track_record(config, chart_data):
    sections = []
    for commodity_ticker, spec in config.items():
        pairs_html = "".join(render_track_pair(p, chart_data) for p in spec["pairs"])
        if not pairs_html:
            continue
        sections.append(f"""
        <section class="track-commodity">
          <h3>{html.escape(spec['name'])} <span class="commodity-ticker">{html.escape(commodity_ticker)}</span></h3>
          {pairs_html}
        </section>""")
    return "".join(sections) or '<p class="empty-state">No chart data yet -- run build_chart_data.py.</p>'


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

    config = load_config()
    chart_data = load_chart_data()
    track_record_html = render_track_record(config, chart_data)

    template_path = os.path.join(os.path.dirname(__file__), "site_template.html")
    with open(template_path) as f:
        template = f.read()

    output = (
        template
        .replace("{{TRACK_RECORD}}", track_record_html)
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
