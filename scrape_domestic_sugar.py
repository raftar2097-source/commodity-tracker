"""
Refreshes data_sources/chinimandi_wholesale_sugar_prices.csv with any new
rows published since the last run.

chinimandi.com has no public API -- the wholesale price table is a
DataTable rendered client-side with server-side pagination, so a plain
HTTP fetch (requests/WebFetch) only sees an empty shell. This uses
Playwright to load the page for real and read the default-rendered rows
(the most recent ~30 days, more than enough buffer to catch up after any
missed run) rather than driving the DataTable to load its full multi-year
history every day -- that bulk pull only needs to happen once (already
done, see data_sources/chinimandi_wholesale_sugar_prices.csv's history).

Idempotent: any row whose date is already in the CSV is skipped, so this
is safe to run more than once for the same day.
"""
import csv
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.chinimandi.com/wholesale-sugar-prices/"
CSV_PATH = Path(__file__).parent / "data_sources" / "chinimandi_wholesale_sugar_prices.csv"
HEADERS = ["Date", "Delhi", "Kanpur", "Raipur", "Mumbai", "Ranchi", "Kolkata", "Guwahati", "Hyderabad", "Chennai"]


def fetch_recent_rows():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#supsystic-table-6 tbody tr", timeout=15000)

        rows = page.eval_on_selector_all(
            "#supsystic-table-6 tbody tr",
            "trs => trs.map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.trim()))"
        )
        browser.close()
    return rows


def load_existing_dates():
    if not CSV_PATH.exists():
        return set()
    with open(CSV_PATH) as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        return {row[0] for row in reader if row and row[0] != "Date"}


def main():
    existing_dates = load_existing_dates()
    rows = fetch_recent_rows()

    new_rows = [r for r in rows if r and r[0] not in existing_dates]

    if not new_rows:
        print("No new rows -- data_sources CSV already up to date.")
        return

    file_exists = CSV_PATH.exists()
    if file_exists and CSV_PATH.stat().st_size > 0:
        with open(CSV_PATH, "rb") as f:
            f.seek(-1, 2)
            ends_with_newline = f.read(1) == b"\n"
        if not ends_with_newline:
            with open(CSV_PATH, "a") as f:
                f.write("\n")

    with open(CSV_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(HEADERS)
        for r in new_rows:
            writer.writerow(r)

    print(f"Appended {len(new_rows)} new row(s): {[r[0] for r in new_rows]}")


if __name__ == "__main__":
    main()
