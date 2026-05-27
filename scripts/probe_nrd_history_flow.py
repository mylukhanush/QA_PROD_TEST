import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler.extractor import _perform_login, _wait_for_page_ready, _wait_for_spinners_gone


load_dotenv()


def _site_env(site_name: str) -> dict:
    prefix = site_name.upper()
    return {
        "url": os.getenv(f"{prefix}_URL"),
        "username": os.getenv(f"{prefix}_USERNAME"),
        "password": os.getenv(f"{prefix}_PASSWORD"),
    }


def _visible_text(page, selector: str) -> str:
    loc = page.locator(selector).first
    if loc.count() == 0:
        return ""
    try:
        return loc.inner_text(timeout=2000).strip()
    except Exception:
        return ""


def _click(page, selector: str):
    loc = page.locator(selector).first
    loc.wait_for(state="visible", timeout=10000)
    try:
        loc.click(timeout=5000)
    except Exception:
        loc.dispatch_event("click")


def main():
    out_dir = Path("captures/nrd-history-probe")
    out_dir.mkdir(parents=True, exist_ok=True)

    env = _site_env("jhs82")
    nrd_url = env["url"].rstrip("/") + "/#/pages/reports-new/nrdhistory"

    result = {"nrd_url": nrd_url}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        login_info = {}
        _perform_login(page, env, login_info)
        _wait_for_page_ready(page)
        page.goto(nrd_url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_page_ready(page)
        _wait_for_spinners_gone(page)

        _click(page, '.multiselect-dropdown:has-text("Select Vehicle") .dropdown-btn')
        _click(page, '.multiselect-dropdown:has-text("Select Vehicle") input[aria-label="multiselect-select-all"]')
        _click(page, 'input[name="dateRange"]')
        _click(page, 'button:has-text("Custom range")')

        may_table = page.locator('table.table-condensed:has(th.month:has-text("May"))').first
        may_table.locator('td.available:not(.off):has-text("1")').first.click(timeout=5000)
        may_table.locator('td.available:not(.off):has-text("12")').first.click(timeout=5000)
        _click(page, 'button:has-text("ok")')

        result["date_range_value"] = page.locator('input[name="dateRange"]').first.input_value(timeout=5000)
        result["vehicle_button_text"] = _visible_text(page, '.multiselect-dropdown:has-text("All") .dropdown-btn')

        _click(page, 'button[title="View"]')
        _wait_for_spinners_gone(page)
        page.wait_for_timeout(2500)

        result["url_after_view"] = page.url
        result["header_text"] = _visible_text(page, 'table[role="grid"] thead')
        result["first_row_text"] = _visible_text(page, 'table[role="grid"] tbody tr')
        result["row_count"] = page.locator('table[role="grid"] tbody tr').count()
        page.screenshot(path=str(out_dir / "flow-result.png"), full_page=True)
        (out_dir / "flow-result.html").write_text(page.content(), encoding="utf-8")
        (out_dir / "flow-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
