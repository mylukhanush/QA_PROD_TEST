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


def _visible_snapshot(page):
    return page.evaluate(
        """
        () => {
          const visible = (el) => {
            const s = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s && s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
          };
          const text = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
          const attrs = (el) => {
            const out = {};
            for (const name of ['id','class','name','type','placeholder','aria-label','role','title','formcontrolname','ng-reflect-placeholder']) {
              const v = el.getAttribute(name);
              if (v) out[name] = v;
            }
            return out;
          };
          const pick = (selector, limit=80) => Array.from(document.querySelectorAll(selector))
            .filter(visible)
            .slice(0, limit)
            .map((el, i) => ({
              i,
              tag: el.tagName.toLowerCase(),
              text: text(el).slice(0, 160),
              attrs: attrs(el),
              html: el.outerHTML.slice(0, 500)
            }));
          return {
            url: location.href,
            title: document.title,
            headings: pick('h1,h2,h3,h4,h5,.page-title,.widget-title,[class*=title],[class*=Title]'),
            labels: pick('label'),
            inputs: pick('input,textarea,select,ng-select,.ng-select,.multiselect-dropdown,[class*=dropdown],[class*=select]'),
            buttons: pick('button,a,[role=button],.btn'),
            tables: pick('table,thead,th,tbody tr'),
            dateHints: pick('input[placeholder*=Date i], input[class*=date i], [class*=date i], bs-datepicker-container, mat-datepicker-content, owl-date-time-container', 120),
          };
        }
        """
    )


def main():
    out_dir = Path("captures/nrd-history-probe")
    out_dir.mkdir(parents=True, exist_ok=True)

    env = _site_env("jhs82")
    reports_url = env["url"].rstrip("/") + "/#/pages/reports-new"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        login_info = {}
        _perform_login(page, env, login_info)
        _wait_for_page_ready(page)

        page.goto(reports_url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_page_ready(page)
        page.screenshot(path=str(out_dir / "reports.png"), full_page=True)

        card = page.locator('div.widget-title:has-text("NRD History"), [class*="widget-title"]:has-text("NRD History")').first
        card.scroll_into_view_if_needed(timeout=5000)
        card.click(timeout=5000)
        page.wait_for_timeout(2500)
        _wait_for_spinners_gone(page)
        page.screenshot(path=str(out_dir / "nrd-history-initial.png"), full_page=True)

        initial = _visible_snapshot(page)
        (out_dir / "nrd-history-initial.html").write_text(page.content(), encoding="utf-8")
        (out_dir / "nrd-history-initial.json").write_text(json.dumps(initial, indent=2), encoding="utf-8")

        # Open the vehicle dropdown and capture the "select all" affordance/options.
        try:
            page.locator('.multiselect-dropdown:has-text("Select Vehicle") .dropdown-btn').first.click(timeout=5000)
            page.wait_for_timeout(1000)
            vehicle_open = _visible_snapshot(page)
            (out_dir / "vehicle-dropdown-open.html").write_text(page.content(), encoding="utf-8")
            (out_dir / "vehicle-dropdown-open.json").write_text(json.dumps(vehicle_open, indent=2), encoding="utf-8")
            page.screenshot(path=str(out_dir / "vehicle-dropdown-open.png"), full_page=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception as exc:
            vehicle_open = {"error": str(exc)}
            (out_dir / "vehicle-dropdown-open.json").write_text(json.dumps(vehicle_open, indent=2), encoding="utf-8")

        # Open the date range picker and capture its controls.
        try:
            page.locator('input[name="dateRange"]').first.click(timeout=5000)
            page.wait_for_timeout(1000)
            date_open = _visible_snapshot(page)
            (out_dir / "date-picker-open.html").write_text(page.content(), encoding="utf-8")
            (out_dir / "date-picker-open.json").write_text(json.dumps(date_open, indent=2), encoding="utf-8")
            page.screenshot(path=str(out_dir / "date-picker-open.png"), full_page=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception as exc:
            date_open = {"error": str(exc)}
            (out_dir / "date-picker-open.json").write_text(json.dumps(date_open, indent=2), encoding="utf-8")

        print(json.dumps({
            "login": login_info,
            "reports_url": reports_url,
            "nrd_url": page.url,
            "counts": {k: len(v) for k, v in initial.items() if isinstance(v, list)},
            "outputs": {
                "initial_json": str(out_dir / "nrd-history-initial.json"),
                "initial_html": str(out_dir / "nrd-history-initial.html"),
                "vehicle_dropdown_json": str(out_dir / "vehicle-dropdown-open.json"),
                "date_picker_json": str(out_dir / "date-picker-open.json"),
                "screenshot": str(out_dir / "nrd-history-initial.png"),
            }
        }, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
