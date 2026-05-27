"""
Crawl ALL report types in the Reports tab and add their selectors to site-map.json.

For each report card on the Reports grid, this script:
  1. Clicks the card to navigate to the report page
  2. Waits for the page to load
  3. Captures all interactive selectors (dropdowns, date pickers, inputs,
     buttons, tables, pagination)
  4. Takes a screenshot
  5. Goes back to the Reports grid and continues with the next card

Usage:
    .venv311\Scripts\python.exe scripts\crawl_all_reports.py
"""
import json
import os
import sys
import re
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from crawler.extractor import _perform_login, _wait_for_page_ready, _wait_for_spinners_gone

load_dotenv()


def _site_env(site_name: str) -> dict:
    prefix = site_name.upper()
    return {
        "url": os.getenv(f"{prefix}_URL"),
        "username": os.getenv(f"{prefix}_USERNAME"),
        "password": os.getenv(f"{prefix}_PASSWORD"),
    }


def _slugify(name: str) -> str:
    """Convert a report card name like 'NRD History' -> 'nrd_history'."""
    s = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower()
    return re.sub(r'\s+', '_', s)


def _capture_page_selectors(page) -> dict:
    """Capture all interactive elements on the current report page via JS."""
    return page.evaluate("""
    () => {
        const visible = (el) => {
            const s = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return s && s.visibility !== 'hidden' && s.display !== 'none'
                && r.width > 0 && r.height > 0;
        };
        const text = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        const attrs = (el) => {
            const out = {};
            for (const name of [
                'id', 'class', 'name', 'type', 'placeholder', 'aria-label',
                'role', 'title', 'formcontrolname', 'ng-reflect-placeholder'
            ]) {
                const v = el.getAttribute(name);
                if (v) out[name] = v;
            }
            return out;
        };
        const pick = (selector, limit = 50) =>
            Array.from(document.querySelectorAll(selector))
                .filter(visible)
                .slice(0, limit)
                .map((el, i) => ({
                    i,
                    tag: el.tagName.toLowerCase(),
                    text: text(el).slice(0, 200),
                    attrs: attrs(el),
                    html: el.outerHTML.slice(0, 400)
                }));

        return {
            url: location.href,
            title: document.title,
            inputs: pick(
                'input,textarea,select,ng-select,.ng-select,' +
                '.multiselect-dropdown,[class*=dropdown],[class*=select]'
            ),
            buttons: pick('button,[role=button],.btn,.form_btn'),
            tables: pick('table,thead,th'),
            pagination: pick('.mat-paginator,.mat-paginator-range-label,[class*=paginator]'),
            dateHints: pick(
                'input[name*=date i],input[class*=date i],' +
                '[class*=date-picker],[class*=daterange],' +
                'bs-datepicker-container,ngx-daterangepicker-material'
            ),
        };
    }
    """)


def _build_elements_from_snapshot(snapshot: dict, report_name: str) -> list:
    """Convert a JS snapshot into site-map element entries."""
    elements = []

    # Multiselect dropdowns (vehicle, tag, etc.)
    for item in snapshot.get("inputs", []):
        cls = item["attrs"].get("class", "")
        item_text = item["text"]

        if "multiselect-dropdown" in cls and item_text:
            short_label = item_text.split("\n")[0].strip()[:40]
            elements.append({
                "label": f"{short_label} dropdown button",
                "selector": f'.multiselect-dropdown:has-text("{short_label}") .dropdown-btn',
                "backup_selector": "",
                "element_type": "dropdown",
                "section": "filters",
                "is_dynamic": False,
                "value_sample": short_label,
                "text_anchor_label": short_label,
            })
            # Add "Select All" checkbox for this dropdown
            elements.append({
                "label": f"{short_label} select all checkbox",
                "selector": f'.multiselect-dropdown:has-text("{short_label}") input[aria-label="multiselect-select-all"]',
                "backup_selector": "",
                "element_type": "checkbox",
                "section": "filters",
                "is_dynamic": False,
                "value_sample": "Select All",
                "text_anchor_label": "Select All",
            })
            continue

        # ng-select dropdowns
        if item["tag"] == "ng-select":
            attrs = item["attrs"]
            label_attr = (
                attrs.get("placeholder") or 
                attrs.get("ng-reflect-placeholder") or 
                attrs.get("formcontrolname") or 
                attrs.get("aria-label") or 
                attrs.get("name")
            )
            lbl = label_attr or (item_text.split("\n")[0].strip()[:40] if item_text else "")
            
            if lbl:
                if label_attr:
                    # Prefer exact attribute match
                    attr_name = "placeholder" if "placeholder" in attrs else ("ng-reflect-placeholder" if "ng-reflect-placeholder" in attrs else ("formcontrolname" if "formcontrolname" in attrs else ("aria-label" if "aria-label" in attrs else "name")))
                    sel = f'ng-select[{attr_name}="{label_attr}"]'
                else:
                    sel = f'ng-select:has-text("{lbl}")'
                    
                elements.append({
                    "label": f"{lbl} dropdown",
                    "selector": sel,
                    "backup_selector": "",
                    "element_type": "dropdown",
                    "section": "filters",
                    "is_dynamic": False,
                    "value_sample": item_text[:60] if item_text else "",
                    "text_anchor_label": lbl,
                })
            continue

        # Date range input
        name = item["attrs"].get("name", "")
        if "date" in name.lower() or "date" in cls.lower():
            elements.append({
                "label": f"{report_name} date range input",
                "selector": f'input[name="{name}"]' if name else f'input[class*="date"]',
                "backup_selector": "",
                "element_type": "input",
                "section": "filters",
                "is_dynamic": False,
                "value_sample": item_text[:60] if item_text else "",
                "text_anchor_label": "Date Range",
            })
            continue

        # Search / filter input
        placeholder = item["attrs"].get("placeholder", "")
        input_id = item["attrs"].get("id", "")
        input_name = item["attrs"].get("name", "")
        if item["tag"] == "input" and (placeholder or input_id):
            if "search" in placeholder.lower() or "filter" in (input_name or "").lower():
                sel = f"input#{input_id}" if input_id else f'input[placeholder="{placeholder}"]'
                elements.append({
                    "label": f"{report_name} search input",
                    "selector": sel,
                    "backup_selector": "",
                    "element_type": "input",
                    "section": "table_tools",
                    "is_dynamic": False,
                    "value_sample": placeholder,
                    "text_anchor_label": "Search",
                })

    # Action buttons (View, Reset, Download, Schedule)
    for item in snapshot.get("buttons", []):
        title = item["attrs"].get("title", "")
        btn_type = item["attrs"].get("type", "")
        if title in ("View", "Reset", "Download", "Schedule"):
            elements.append({
                "label": f"{title} report button",
                "selector": f'button[title="{title}"]',
                "backup_selector": "",
                "element_type": "button",
                "section": "actions",
                "is_dynamic": False,
                "value_sample": title,
                "text_anchor_label": title,
            })

    # Table
    for item in snapshot.get("tables", []):
        if item["tag"] == "table":
            role = item["attrs"].get("role", "")
            cls = item["attrs"].get("class", "")
            sel = 'table[role="grid"]' if role == "grid" else "table"
            elements.append({
                "label": f"{report_name} report table",
                "selector": sel,
                "backup_selector": "",
                "element_type": "table",
                "section": "results",
                "is_dynamic": True,
                "value_sample": item["text"][:80],
                "text_anchor_label": f"{report_name} table",
            })
            elements.append({
                "label": f"{report_name} first data row",
                "selector": f"{sel} tbody tr",
                "backup_selector": "",
                "element_type": "table_row",
                "section": "results",
                "is_dynamic": True,
                "value_sample": "",
                "text_anchor_label": f"{report_name} data row",
            })
            break  # Only capture first table

    # Pagination
    for item in snapshot.get("pagination", []):
        cls = item["attrs"].get("class", "")
        if "range-label" in cls:
            elements.append({
                "label": f"{report_name} pagination info",
                "selector": ".mat-paginator-range-label",
                "backup_selector": "",
                "element_type": "text",
                "section": "results",
                "is_dynamic": True,
                "value_sample": item["text"][:40],
                "text_anchor_label": "Items per page",
            })

    return elements


def main():
    out_dir = Path("captures/all-reports-crawl")
    out_dir.mkdir(parents=True, exist_ok=True)

    env = _site_env("jhs82")
    reports_url = env["url"].rstrip("/") + "/#/pages/reports-new"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()

        # Login
        print("[1] Logging in to jhs82...")
        login_info = {}
        _perform_login(page, env, login_info)
        _wait_for_page_ready(page)
        print(f"    Logged in. URL: {page.url}")

        # Navigate to Reports grid
        print("[2] Navigating to Reports page...")
        page.goto(reports_url, wait_until="domcontentloaded", timeout=30000)
        _wait_for_page_ready(page)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(out_dir / "reports-grid.png"), full_page=True)

        # Collect all report cards
        print("[3] Collecting report card names...")
        cards = page.evaluate("""
        () => {
            const cards = document.querySelectorAll(
                '.widget-title, [class*="report-title"], [class*="card-title"], ' +
                '.reportTitle, .report-card-title, .report-name'
            );
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none';
            };
            return Array.from(cards)
                .filter(visible)
                .map(el => ({
                    text: (el.innerText || el.textContent || '').trim(),
                    tag: el.tagName.toLowerCase(),
                    className: el.className
                }))
                .filter(c => c.text.length > 1);
        }
        """)

        print(f"    Found {len(cards)} report cards:")
        for c in cards:
            print(f"      - {c['text']}")

        # Load existing site-map
        site_map_path = Path("site-map.json")
        site_map = json.loads(site_map_path.read_text(encoding="utf-8"))

        crawled = 0
        skipped = 0
        errors = []

        for card_info in cards:
            card_name = card_info["text"]
            slug = "reports_" + _slugify(card_name)

            # Skip NRD History since we already have it
            if slug == "reports_nrd_history":
                print(f"\n[SKIP] {card_name} — already in site-map")
                skipped += 1
                continue

            print(f"\n[CRAWL] {card_name} (slug: {slug})")

            try:
                # Navigate back to reports grid
                page.goto(reports_url, wait_until="domcontentloaded", timeout=30000)
                _wait_for_page_ready(page)
                page.wait_for_timeout(1500)

                # Click the report card
                card_loc = page.locator(
                    f'.widget-title:has-text("{card_name}"), '
                    f'[class*="report-title"]:has-text("{card_name}"), '
                    f'[class*="card-title"]:has-text("{card_name}")'
                ).first
                card_loc.scroll_into_view_if_needed(timeout=5000)
                card_loc.click(timeout=5000)

                # Wait for the report page to load
                page.wait_for_timeout(3000)
                _wait_for_spinners_gone(page)
                _wait_for_page_ready(page)

                current_url = page.url
                print(f"    URL: {current_url}")

                # Take screenshot
                screenshot_path = str(out_dir / f"{slug}.png")
                page.screenshot(path=screenshot_path, full_page=True)

                # Capture selectors
                snapshot = _capture_page_selectors(page)

                # Save raw JSON
                (out_dir / f"{slug}.json").write_text(
                    json.dumps(snapshot, indent=2), encoding="utf-8"
                )

                # Build structured elements
                elements = _build_elements_from_snapshot(snapshot, card_name)

                # Determine the nav selector
                nav_selector = f'div.widget-title:has-text("{card_name}")'

                # Build the page entry
                page_entry = {
                    "url": current_url,
                    "nav_selector": nav_selector,
                    "source_site": "jhs82",
                    "reuse_selectors_for_sites": ["jhs81", "jhs82", "jhs83", "jhs84"],
                    "workflow_note": (
                        f"For {card_name} report tests: login, open Reports, "
                        f"click {card_name}, select vehicles/date range, click View, "
                        f"then assert table rows/data."
                    ),
                    "loading_indicators": [
                        ".loading", ".loader", ".loaderBack",
                        '[class*="spinner"]'
                    ],
                    "api_endpoints": [],
                    "elements": elements,
                }

                # Add common date picker elements if date input found
                has_date = any(e["section"] == "filters" and "date" in e["label"].lower()
                               for e in elements)
                if has_date:
                    page_entry["elements"].extend([
                        {
                            "label": "Date picker custom range button",
                            "selector": 'button:has-text("Custom range")',
                            "backup_selector": "",
                            "element_type": "button",
                            "section": "date_picker",
                            "is_dynamic": False,
                            "value_sample": "Custom range",
                            "text_anchor_label": "Custom range",
                        },
                        {
                            "label": "Date picker OK button",
                            "selector": 'button:has-text("ok")',
                            "backup_selector": "",
                            "element_type": "button",
                            "section": "date_picker",
                            "is_dynamic": False,
                            "value_sample": "ok",
                            "text_anchor_label": "ok",
                        },
                    ])

                # Add the Reports sidebar nav link if not already present
                has_reports_nav = any(
                    e["label"] == "Reports sidebar nav"
                    for e in page_entry["elements"]
                )
                if not has_reports_nav:
                    page_entry["elements"].insert(0, {
                        "label": "Reports sidebar nav",
                        "selector": '.nav-link:has-text("Reports")',
                        "backup_selector": "",
                        "element_type": "link",
                        "section": "navigation",
                        "is_dynamic": False,
                        "value_sample": "Reports",
                        "text_anchor_label": "Reports",
                    })
                # Add nav selector for this specific report card
                page_entry["elements"].insert(1, {
                    "label": f"{card_name} report card",
                    "selector": nav_selector,
                    "backup_selector": "",
                    "element_type": "button",
                    "section": "reports_grid",
                    "is_dynamic": False,
                    "value_sample": card_name,
                    "text_anchor_label": card_name,
                })

                site_map["pages"][slug] = page_entry
                crawled += 1
                print(f"    [OK] Captured {len(elements)} elements")

            except Exception as exc:
                print(f"    [ERR] ERROR: {exc}")
                errors.append({"report": card_name, "error": str(exc)})

        # Save updated site-map
        print(f"\n[4] Saving site-map.json...")
        site_map_path.write_text(json.dumps(site_map, indent=2), encoding="utf-8")
        print(f"    [OK] Saved. Crawled: {crawled}, Skipped: {skipped}, Errors: {len(errors)}")
        if errors:
            print("    Errors:")
            for e in errors:
                print(f"      - {e['report']}: {e['error']}")

        # Summary
        summary = {
            "crawled": crawled,
            "skipped": skipped,
            "errors": errors,
            "reports_found": [c["text"] for c in cards],
            "pages_in_sitemap": list(site_map["pages"].keys()),
        }
        (out_dir / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )

        browser.close()
        print("\n[DONE] All reports crawled!")


if __name__ == "__main__":
    main()
