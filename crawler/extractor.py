"""
Site Crawler — Playwright-based element extractor.

Logs in to a target site, visits every page, and captures all meaningful
selectors, labels, values, and loading indicators.  Produces site-map.json
and seeds the site_elements table.
"""
import json
import os
import re
from collections import deque
from datetime import datetime, timedelta, timezone

import time
from playwright.sync_api import sync_playwright
from app.logging_config import log_event

from db import db
from db.models import Site, SiteElement


# ── Helpers ───────────────────────────────────────────────────────

def _site_env(site_name: str, jhs_credentials=None):
    """Load site credentials from environment variables."""
    prefix = site_name.upper()  # JHS81, JHS82, …
    if jhs_credentials and jhs_credentials.get("username") and jhs_credentials.get("password"):
        return {
            "url": os.getenv(f"{prefix}_URL"),
            "username": jhs_credentials["username"],
            "password": jhs_credentials["password"],
        }
    return {
        "url": os.getenv(f"{prefix}_URL"),
        "username": os.getenv(f"{prefix}_USERNAME"),
        "password": os.getenv(f"{prefix}_PASSWORD"),
    }


def _wait_for_spinners_gone(page):
    """Wait for common loading indicators to disappear."""
    spinner_selectors = [
        ".spinner", ".loading", "[class*='spinner']",
        "[class*='loading']", ".skeleton", "[class*='skeleton']",
        "[role='progressbar']",
    ]
    for sel in spinner_selectors:
        try:
            locator = page.locator(sel)
            if locator.count() > 0 and locator.first.is_visible():
                locator.first.wait_for(state="hidden", timeout=2000)
        except Exception:
            pass


def _wait_for_page_ready(page):
    """Wait for page to be usable. Uses domcontentloaded first, then tries
    networkidle with a short timeout (maps pages never reach networkidle)."""
    page.wait_for_load_state("domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # Maps/analytics keep firing — that's OK
    _wait_for_spinners_gone(page)


def _first_visible_locator(page, selectors):
    """Return the first visible locator from a list of selectors."""
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for idx in range(min(count, 10)):
                candidate = locator.nth(idx)
                if candidate.is_visible():
                    return candidate, selector
        except Exception:
            continue
    return None, None


def _is_meaningful_metric_value(label_text: str, value_text: str) -> bool:
    """Return True for short metric-like values and False for noisy UI text."""
    label_text = (label_text or "").strip()
    value_text = (value_text or "").strip()

    if len(label_text) < 2:
        return False
    if not value_text:
        return False
    if len(value_text) > 50:
        return False
    if label_text.lower() == value_text.lower():
        return False
    if not re.search(r"\w", value_text):
        return False

    blocked_values = {
        "click here", "view", "edit", "delete", "more", "filter", "search"
    }
    if value_text.strip().lower() in blocked_values:
        return False

    short_status_words = {"active", "inactive", "online", "offline"}
    value_lower = value_text.strip().lower()
    has_digit = bool(re.search(r"\d", value_text))
    is_short_status = value_lower in short_status_words

    return has_digit or is_short_status


# ── Main Extraction Logic ────────────────────────────────────────

def _extract_elements(page, page_name: str, elements=None, discovered_selectors=None,
                      budget_ms: int = 20000):
    """
    Extract all visible elements that contain meaningful values.
    budget_ms caps the total time spent on generic card strategies so that
    map/live pages (with thousands of DOM nodes) don't block the crawl.
    """
    import time
    deadline = time.monotonic() + budget_ms / 1000

    if elements is None:
        elements = []
    if discovered_selectors is None:
        discovered_selectors = set()

    # ── Page headings (always fast, run first so budget doesn't starve them) ──
    try:
        for hsel in ["h1", "h2", "h3", "h4", "h5", "h6", ".page-title", ".section-title",
                     "[class*='page-title']", "[class*='section-heading']"]:
            try:
                hdrs = page.locator(hsel)
                for i in range(min(hdrs.count(), 10)):
                    h = hdrs.nth(i)
                    try:
                        if not h.is_visible(timeout=300):
                            continue
                        txt = (h.text_content(timeout=1000) or "").strip()
                        if not txt or len(txt) < 2 or len(txt) > 100:
                            continue
                        sel = f'{hsel}:has-text("{txt.replace(chr(34), chr(39))}")'
                        if sel not in discovered_selectors:
                            discovered_selectors.add(sel)
                            elements.append({
                                "label": txt,
                                "selector": sel,
                                "backup_selector": "",
                                "element_type": "heading",
                                "section": "page_structure",
                                "is_dynamic": False,
                                "value_sample": txt,
                                "text_anchor_label": txt,
                            })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    # ── Label elements (used heavily in Command Centre and form pages) ──
    try:
        label_els = page.locator("label")
        _blocked_labels = {"username", "password", "email", "search", "filter", "date", "from", "to", "select"}
        for i in range(min(label_els.count(), 50)):
            lbl = label_els.nth(i)
            try:
                if not lbl.is_visible(timeout=300):
                    continue
                txt = (lbl.text_content(timeout=1000) or "").strip().rstrip("*").strip()
                if not txt or len(txt) < 2 or len(txt) > 60:
                    continue
                if txt.lower() in _blocked_labels:
                    continue
                sel = f'label:has-text("{txt.replace(chr(34), chr(39))}")'
                if sel not in discovered_selectors:
                    discovered_selectors.add(sel)
                    elements.append({
                        "label": txt,
                        "selector": sel,
                        "backup_selector": "",
                        "element_type": "label",
                        "section": "form_labels",
                        "is_dynamic": False,
                        "value_sample": txt,
                        "text_anchor_label": txt,
                    })
            except Exception:
                continue
    except Exception:
        pass

    # ── Report card / widget titles (div.widget-title etc.) ──
    try:
        for wsel in ["div.widget-title", "[class*='widget-title']", "[class*='widget-name']",
                     "[class*='report-title']", "[class*='card-label']",
                     "div.TableHeader", "[class*='TableHeader']", "[class*='table-header-title']"]:
            try:
                wels = page.locator(wsel)
                for i in range(min(wels.count(), 40)):
                    wel = wels.nth(i)
                    try:
                        if not wel.is_visible(timeout=300):
                            continue
                        txt = (wel.text_content(timeout=1000) or "").strip()
                        if not txt or len(txt) < 2 or len(txt) > 80:
                            continue
                        esel = f'{wsel}:has-text("{txt.replace(chr(34), chr(39))}")'
                        if esel not in discovered_selectors:
                            discovered_selectors.add(esel)
                            elements.append({
                                "label": txt,
                                "selector": esel,
                                "backup_selector": "",
                                "element_type": "section_title",
                                "section": "page_sections",
                                "is_dynamic": False,
                                "value_sample": txt,
                                "text_anchor_label": txt,
                            })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    # ── Angular Material accordion / expansion panel titles ──
    try:
        for msel in ["mat-panel-title", "mat-expansion-panel-header .mat-content span",
                     ".mat-expansion-panel-header-title"]:
            try:
                mpanels = page.locator(msel)
                for i in range(min(mpanels.count(), 30)):
                    mp = mpanels.nth(i)
                    try:
                        if not mp.is_visible(timeout=300):
                            continue
                        txt = (mp.text_content(timeout=1000) or "").strip()
                        if not txt or len(txt) < 2 or len(txt) > 100:
                            continue
                        esel = f'{msel}:has-text("{txt.replace(chr(34), chr(39))}")'
                        if esel not in discovered_selectors:
                            discovered_selectors.add(esel)
                            elements.append({
                                "label": txt,
                                "selector": esel,
                                "backup_selector": f'mat-panel-title:has-text("{txt}")',
                                "element_type": "panel_title",
                                "section": "accordion_panels",
                                "is_dynamic": False,
                                "value_sample": txt,
                                "text_anchor_label": txt,
                            })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    # ── Fieldset legends (roles/permission pages) ──
    try:
        legends = page.locator("fieldset legend, fieldset > .legend, .form-group > .group-label")
        for i in range(min(legends.count(), 20)):
            leg = legends.nth(i)
            try:
                if not leg.is_visible(timeout=300):
                    continue
                txt = (leg.text_content(timeout=1000) or "").strip()
                if not txt or len(txt) < 2 or len(txt) > 80:
                    continue
                esel = f'legend:has-text("{txt.replace(chr(34), chr(39))}")'
                if esel not in discovered_selectors:
                    discovered_selectors.add(esel)
                    elements.append({
                        "label": txt,
                        "selector": esel,
                        "backup_selector": "",
                        "element_type": "form_section",
                        "section": "fieldset",
                        "is_dynamic": False,
                        "value_sample": txt,
                        "text_anchor_label": txt,
                    })
            except Exception:
                continue
    except Exception:
        pass

    # ── Meaningful action buttons (Add, Create, Fetch, etc. — not map/utility) ──
    _UTILITY_BTNS = {
        "map", "satellite", "keyboard shortcuts", "refresh", "go", "reset",
        "save", "cancel", "close", "ok", "yes", "no", "submit", "back",
        "next", "prev", "previous", "search", "filter", "clear", "apply",
        "export", "import", "upload", "download", "print", "help", "info",
        "details", "view", "edit", "delete", "remove", "+", "×", "x",
    }
    try:
        btns = page.locator("button, a.btn, a[class*='btn']")
        for i in range(min(btns.count(), 60)):
            btn = btns.nth(i)
            try:
                if not btn.is_visible(timeout=200):
                    continue
                txt = (btn.text_content() or "").strip()
                if not txt or len(txt) < 3 or len(txt) > 60:
                    continue
                if txt.lower() in _UTILITY_BTNS:
                    continue
                # Keep action buttons like "+ Add Role", "Fetch EWB", "Create Geofence"
                esel = f'button:has-text("{txt.replace(chr(34), chr(39))}")'
                if esel not in discovered_selectors:
                    discovered_selectors.add(esel)
                    elements.append({
                        "label": txt,
                        "selector": esel,
                        "backup_selector": "",
                        "element_type": "action_button",
                        "section": "page_actions",
                        "is_dynamic": False,
                        "value_sample": txt,
                        "text_anchor_label": txt,
                    })
            except Exception:
                continue
    except Exception:
        pass

    # ── Count badges / number chips ──
    try:
        badge_sels = [".badge", "[class*='badge']", "[class*='count-badge']",
                      ".chip", "[class*='count-chip']", "span[class*='total']"]
        for bsel in badge_sels:
            try:
                badges = page.locator(bsel)
                for i in range(min(badges.count(), 20)):
                    b = badges.nth(i)
                    try:
                        if not b.is_visible(timeout=300):
                            continue
                        txt = (b.text_content(timeout=1000) or "").strip()
                        if not txt or not re.search(r'\d', txt):
                            continue
                        dedup_key = bsel + f":nth-of-type({i+1})"
                        if dedup_key not in discovered_selectors:
                            discovered_selectors.add(dedup_key)
                            elements.append({
                                "label": f"Badge: {txt}",
                                "selector": bsel,
                                "backup_selector": "",
                                "element_type": "badge",
                                "section": "count_badge",
                                "is_dynamic": True,
                                "value_sample": txt,
                                "text_anchor_label": txt,
                            })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass

    # Metric / stat cards — use JS-based scan to avoid per-locator IPC overhead
    card_strategies = [
        {"container": ".card, .stat-card, .metric-card, [class*='card'], [class*='stat'], [class*='metric']"},
        {"container": ".dashboard-item, .widget, .panel, [class*='widget']"},
        {"container": ".col, .column, [class*='col-']"},
    ]

    for strategy in card_strategies:
        if time.monotonic() > deadline:
            break
        try:
            containers = page.locator(strategy["container"])
            count = min(containers.count(), 50)   # reduced from 100
            for i in range(count):
                if time.monotonic() > deadline:
                    break
                container = containers.nth(i)
                if not container.is_visible():
                    continue

                # Try to find label and value pairs
                label_text = ""
                value_text = ""
                value_sel = ""

                for lsel in ["h3", "h4", "h5", ".card-title", ".label", ".title", "small", "span.text-muted", ".card-header"]:
                    try:
                        lbl = container.locator(lsel).first
                        if lbl.is_visible():
                            label_text = lbl.text_content().strip()
                            break
                    except Exception:
                        continue

                for vsel in [".value", ".number", ".count", "h2", "h1", ".card-value", ".metric-value", ".stat-value", "span.h2", "span.h3", "strong"]:
                    try:
                        val = container.locator(vsel).first
                        if val.is_visible():
                            value_text = val.text_content().strip()
                            value_sel = vsel
                            break
                    except Exception:
                        continue

                if not _is_meaningful_metric_value(label_text, value_text):
                    continue

                if label_text and value_text and value_sel:
                    try:
                        css = container.locator(value_sel).first.evaluate(
                            """el => {
                                let path = [];
                                while (el && el !== document.body) {
                                    let selector = el.tagName.toLowerCase();
                                    if (el.id) {
                                        selector = '#' + el.id;
                                        path.unshift(selector);
                                        break;
                                    }
                                    if (el.className && typeof el.className === 'string') {
                                        const classes = el.className.trim().split(/\\s+/).filter(c => c.length < 30).slice(0, 3);
                                        if (classes.length) selector += '.' + classes.join('.');
                                    }
                                    const parent = el.parentElement;
                                    if (parent) {
                                        const siblings = Array.from(parent.children).filter(c => c.tagName === el.tagName);
                                        if (siblings.length > 1) {
                                            const idx = siblings.indexOf(el) + 1;
                                            selector += ':nth-of-type(' + idx + ')';
                                        }
                                    }
                                    path.unshift(selector);
                                    el = el.parentElement;
                                }
                                return path.join(' > ');
                            }"""
                        )
                    except Exception:
                        css = f"*:has-text('{label_text}') ~ * {value_sel}, *:has-text('{label_text}') + {value_sel}"

                    if css not in discovered_selectors:
                        discovered_selectors.add(css)
                        elements.append({
                            "label": label_text,
                            "selector": css,
                            "backup_selector": f"//text()[contains(.,'{label_text}')]/ancestor::*[1]",
                            "element_type": "metric_card",
                            "section": "summary cards",
                            "is_dynamic": False,
                            "value_sample": value_text,
                            "text_anchor_label": label_text,
                        })
        except Exception:
            continue

    # Table rows
    if time.monotonic() < deadline:
      try:
        tables = page.locator("table")
        for t_idx in range(min(tables.count(), 5)):
            if time.monotonic() > deadline:
                break
            tbl = tables.nth(t_idx)
            if not tbl.is_visible():
                continue
            headers = []
            try:
                header_cells = tbl.locator("thead th")
                for h_idx in range(header_cells.count()):
                    header_text = header_cells.nth(h_idx).text_content().strip()
                    headers.append(header_text)
            except Exception:
                headers = []
            # Always extract column headers (present even when table is empty)
            for h_idx, hdr in enumerate(headers):
                if not hdr:
                    continue
                hdr_sel = f'table:nth-of-type({t_idx + 1}) thead th:nth-child({h_idx + 1})'
                if hdr_sel not in discovered_selectors:
                    discovered_selectors.add(hdr_sel)
                    elements.append({
                        "label": f"Column: {hdr}",
                        "selector": hdr_sel,
                        "backup_selector": f'th:has-text("{hdr}")',
                        "element_type": "table_header",
                        "section": "table",
                        "is_dynamic": False,
                        "value_sample": hdr,
                        "text_anchor_label": hdr,
                    })

            rows = tbl.locator("tbody tr")
            for r_idx in range(min(rows.count(), 20)):
                if time.monotonic() > deadline:
                    break
                row = rows.nth(r_idx)
                cells = row.locator("td")
                if cells.count() >= 2:
                    first_cell = cells.first.text_content().strip()
                    for c_idx in range(1, cells.count()):
                        val = cells.nth(c_idx).text_content().strip()
                        if val:
                            selector = f"table:nth-of-type({t_idx + 1}) tbody tr:nth-child({r_idx + 1}) td:nth-child({c_idx + 1})"
                            header_label = headers[c_idx].strip() if c_idx < len(headers) and headers[c_idx].strip() else ""
                            label = f"{first_cell} — {header_label}" if header_label else first_cell
                            if selector not in discovered_selectors:
                                discovered_selectors.add(selector)
                                elements.append({
                                    "label": label,
                                    "selector": selector,
                                    "backup_selector": "",
                                    "element_type": "table_row",
                                    "section": "table",
                                    "is_dynamic": False,
                                    "value_sample": val,
                                    "text_anchor_label": first_cell,
                                })
      except Exception:
          pass

    # Angular-specific repeating metric cards (status-card, vehicle-count-box, etc.)
    _extract_angular_status_cards(page, elements, discovered_selectors)

    return elements


def _detect_dynamic(page, elements):
    """Dynamic detection disabled — adds minutes of IPC overhead per page.
    Elements from Angular metric cards are already marked is_dynamic=True."""
    return elements


def _wait_for_api_data(page, timeout=8000):
    """
    Wait until Angular's ngOnInit HTTP calls have populated metric cards.
    Looks for any recognised value element that is non-empty AND not '0'.
    Gracefully times out on pages that have no metric cards.
    """
    try:
        page.wait_for_function(
            """() => {
                const sels = [
                    'div.status-count',
                    'div.vehicle-count-box h1',
                    '.metric-value', '.stat-value', '.count-value',
                    '.card-value', '.number-value',
                ];
                for (const s of sels) {
                    const els = document.querySelectorAll(s);
                    for (const el of els) {
                        const t = (el.textContent || '').trim();
                        if (t && t !== '0' && /^\d/.test(t)) return true;
                    }
                }
                return false;
            }""",
            timeout=timeout,
        )
    except Exception:
        pass  # Fine — some pages have no metric cards


# Known Angular repeating card patterns:  (container_sel, value_child_sel, section_label)
_ANGULAR_CARD_PATTERNS = [
    ("div.status-card",        "div.status-count",   "Vehicle Status"),
    ("div.vehicle-count-box",  "h1",                 "Live Status"),
    ("div.device-count-box",   "h1",                 "Device Status"),
    ("div.count-box",          "h1",                 "Count"),
    ("div.count-box",          ".count-value",       "Count"),
    (".summary-card",          ".summary-value",     "Summary"),
    (".kpi-card",              ".kpi-value",         "KPI"),
    (".stat-item",             ".stat-number",       "Stats"),
    ("li.count-item",          "h2",                 "Count"),
    ("li.count-item",          "h3",                 "Count"),
]


def _extract_angular_status_cards(page, elements, discovered_selectors):
    """
    Extract Angular-style repeating metric cards using :has-text anchors.
    Produces short, stable selectors instead of deep nth-of-type chains.
    """
    for container_sel, value_sel, section in _ANGULAR_CARD_PATTERNS:
        try:
            cards = page.locator(container_sel)
            n = cards.count()
            if n == 0:
                continue
            for i in range(min(n, 30)):
                card = cards.nth(i)
                try:
                    if not card.is_visible(timeout=500):
                        continue
                except Exception:
                    continue

                value_text = ""
                try:
                    val_loc = card.locator(value_sel).first
                    value_text = (val_loc.text_content(timeout=2000) or "").strip()
                except Exception:
                    pass

                full_text = ""
                try:
                    full_text = (card.text_content(timeout=2000) or "").strip()
                except Exception:
                    continue

                # Label = card text minus the numeric value
                label_text = re.sub(r'\s+', ' ', full_text.replace(value_text, "")).strip()
                if not label_text or len(label_text) > 80:
                    continue

                label_escaped = label_text.replace('"', '\\"')
                selector = f'{container_sel}:has-text("{label_escaped}") {value_sel}'
                if selector in discovered_selectors:
                    continue

                discovered_selectors.add(selector)
                elements.append({
                    "label": label_text,
                    "selector": selector,
                    "backup_selector": f'{container_sel}:nth-child({i + 1}) {value_sel}',
                    "element_type": "metric_card",
                    "section": section,
                    "is_dynamic": True,
                    "value_sample": value_text,
                    "text_anchor_label": label_text,
                })
        except Exception:
            continue


# Selectors to look for UI tabs / sub-panels on a page
_TAB_SELECTORS = [
    "[role='tab']",
    ".nav-tabs .nav-link",
    ".nav-tabs li a",
    ".tab-link",
    ".tab-btn",
    ".mat-tab-label",
    ".p-tabview-nav li a",
    "ul.nav.nav-pills li a",
    "[class*='tab-header'] [role='tab']",
    "a[data-toggle='tab']",
]


def _discover_tabs(page):
    """
    Return a list of (label, click_selector) for all visible tab buttons on the page.
    """
    seen = set()
    tabs = []
    for sel in _TAB_SELECTORS:
        try:
            items = page.locator(sel)
            count = items.count()
            for i in range(count):
                item = items.nth(i)
                try:
                    if not item.is_visible(timeout=300):
                        continue
                except Exception:
                    continue
                label = (item.text_content() or "").strip()
                if label and label not in seen and len(label) < 80:
                    seen.add(label)
                    escaped = label.replace('"', '\\"')
                    tabs.append((label, f'{sel}:has-text("{escaped}")'))
        except Exception:
            continue
    return tabs


def _capture_api_endpoints(endpoints):
    """Deduplicate and generalize captured response URLs."""
    unique = []
    seen_patterns = set()
    for ep in endpoints:
        # Replace UUIDs and numeric IDs with wildcards
        pattern = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '*', ep)
        pattern = re.sub(r'/\d+', '/*', pattern)
        if pattern not in seen_patterns:
            seen_patterns.add(pattern)
            unique.append(pattern)

    return unique


# ── Login ─────────────────────────────────────────────────────────

def _perform_login(page, site_env, login_info):
    """
    Log in to the site. Returns login metadata for site-map.json.
    Handles the Angular SPA flow:
      1. Navigate → wait for Angular boot → click landing Login button (if present)
         → fill form → Send OTP → fill OTP → Login
    """
    url = site_env["url"]
    page.goto(url, wait_until="domcontentloaded")

    # ── Step 0: Check if already logged in (via storage_state) ──────
    success_sel = ".sidebar-link, a[href*='dashboard'], .main-header, a[href*='reports']"
    try:
        page.wait_for_selector(success_sel, state="visible", timeout=3000)
        print("[CRAWLER] Already logged in via storage state. Skipping login form steps.", flush=True)
        login_info.update({
            "url": page.url,
            "username_selector": "stored",
            "password_selector": "stored",
            "submit_selector": "stored",
            "error_selector": "stored",
            "error_text_contains": "stored",
        })
        return
    except Exception:
        pass

    # ── Step 1: Wait for Angular to boot ─────────────────────────
    try:
        page.wait_for_function(
            """() => document.querySelectorAll('input, button, a').length > 0""",
            timeout=30000,
        )
    except Exception:
        pass

    # ── Step 2: Click landing Login button if present ─────────────
    # Some sites show a landing page first; others go directly to the auth form.
    try:
        landing_login = page.locator(
            'a:has-text("Login"), button:has-text("Login"), '
            'a:has-text("Sign in"), button:has-text("Sign in"), '
            '[routerlink*="login"], [href*="login"], [href*="auth"]'
        )
        if landing_login.count() > 0 and landing_login.first.is_visible():
            landing_login.first.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
    except Exception:
        pass

    # ── Step 3: Wait for login form to render ─────────────────────
    try:
        page.wait_for_function(
            """() => {
                const inputs = document.querySelectorAll('input');
                return inputs.length >= 2;
            }""",
            timeout=30000,
        )
    except Exception:
        print("[WARN] Login form did not fully render in time; proceeding with visible inputs.")

    # ── Step 4: Identify selectors ────────────────────────────────
    username_candidates = [
        "input.form-control",
        'input#username',
        'input[id*="user" i]',
        'input[type="text"]',
        'input[type="email"]',
        'input[placeholder*="username" i]',
        'input[placeholder*="email" i]',
        'input[name*="user" i]',
        'input[name*="email" i]',
        'input:not([type="password"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]):not([type="hidden"])',
    ]
    password_candidates = [
        "input#password-field",
        'input[id*="pass" i]',
        'input[type="password"]',
        'input[placeholder*="password" i]',
        'input[name*="password" i]',
        'input[name*="pass" i]',
    ]

    # Try a list of common submit buttons (Send OTP, Login, Sign in, submit inputs)
    submit_candidates = [
        "button.login_btn",
        'button:has-text("Send OTP")',
        'button:has-text("Send SMS")',
        'button:has-text("Verify")',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
        'button[type="submit"]',
        'input[type="submit"]',
        'button.btn-primary',
        'button.btn'
    ]

    username_field, username_sel = _first_visible_locator(page, username_candidates)
    password_field, password_sel = _first_visible_locator(page, password_candidates)
    submit_field, submit_sel = _first_visible_locator(page, submit_candidates)

    if not username_field:
        raise ValueError("Username field not found on login form")
    if not password_field:
        raise ValueError("Password field not found on login form")

    # Fallback submit selector if nothing matched above
    if not submit_sel:
        submit_sel = 'button:has-text("Login"), button:has-text("Sign in"), button[type="submit"]'

    login_url = page.url
    error_sel = '.error, .alert-danger, .error-message, [class*="error"], [role="alert"], .toast-error, .invalid-feedback'

    login_info.update({
        "url": login_url,
        "username_selector": username_sel,
        "password_selector": password_sel,
        "submit_selector": submit_sel,
        "error_selector": error_sel,
        "error_text_contains": "invalid",
    })

    # ── Step 5: Fill username ─────────────────────────────────────
    username_field.click()
    username_field.fill("")
    username_field.type(site_env["username"], delay=30)

    # ── Step 6: Fill password ─────────────────────────────────────
    password_field.click()
    password_field.fill("")
    password_field.type(site_env["password"], delay=30)

    # ── Step 7: Click "Send OTP" ──────────────────────────────────
    page.locator(submit_sel).first.click()
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

    # ── Step 8: Wait for OTP field and fill it ────────────────────
    otp_sel = None
    try:
        page.wait_for_function(
            """() => {
                const el = document.querySelector('input#otp_Email') ||
                           document.querySelector('input[id*="otp"]') ||
                           document.querySelector('input[name="otp"]');
                return el !== null && el.offsetParent !== null;
            }""",
            timeout=15000,
        )
    except Exception:
        pass

    for sel in ['input#otp_Email', 'input[id*="otp"]', 'input[name="otp"]']:
        try:
            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                otp_sel = sel
                break
        except Exception:
            continue

    if otp_sel:
        otp_field = page.locator(otp_sel).first
        otp_field.click()
        otp_field.fill("")
        otp_field.type("123456", delay=50)

        # ── Step 9: Click "Login" ──────────────────────────────────
        page.locator(submit_sel).first.click()
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    # ── Step 10: Wait for successful redirect ─────────────────────
    try:
        page.wait_for_function(
            """() => {
                const href = window.location.href.toLowerCase();
                return (
                    (href.includes('#/pages/dashboard/') || href.includes('aggregate-dashboard')) &&
                    !href.includes('login') &&
                    !href.includes('auth')
                );
            }""",
            timeout=20000,
        )
        current_href = page.url.lower()
        login_info["success_indicator"] = {
            "type": "url_contains",
            "value": "#/pages/dashboard/" if "#/pages/dashboard/" in current_href else "dashboard",
        }
    except Exception:
        try:
            page.wait_for_selector(
                ".dashboard, [class*='dashboard'], .map-container, [class*='map'], .sidebar, [class*='sidebar']",
                state="visible",
                timeout=10000,
            )
            login_info["success_indicator"] = {
                "type": "element_visible",
                "value": ".dashboard",
            }
        except Exception:
            login_info["success_indicator"] = {
                "type": "url_contains",
                "value": page.url,
            }

    return login_info


def _is_login_page(page) -> bool:
    """Heuristic to detect an authentication/login form that may appear
    during a crawl (modal or full page). Returns True when the page
    appears to be a login/auth screen so the crawler can attempt re-login.
    """
    try:
        # Look for common auth container markers
        auth_containers = [
            '.login-form', '.auth-container', '.sign-in', '.auth', '#login', 'form.login'
        ]
        for sel in auth_containers:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible(timeout=200):
                    return True
            except Exception:
                pass

        # Buttons like 'Send OTP', 'Send SMS', 'Verify' or 'Login' together
        # with mobile/email inputs are strong indicators of an auth flow.
        try:
            has_action = page.locator("button:has-text('Send OTP'), button:has-text('Send SMS'), button:has-text('Verify'), button:has-text('Login'), button:has-text('Sign in')").count() > 0
        except Exception:
            has_action = False

        try:
            has_contact_input = page.locator("input[placeholder*='mobile' i], input[placeholder*='email' i], input[name*='mobile' i], input[name*='email' i], input[type='email']").count() > 0
        except Exception:
            has_contact_input = False

        if has_action and has_contact_input:
            return True

        # Tab-based auth (Email / Mobile) is a common login widget.
        # Only treat it as auth when accompanied by contact inputs and an
        # auth action inside the same region to avoid false positives.
        try:
            tab_count = page.locator("[role='tab']").count()
            if tab_count >= 2:
                try:
                    parent_has_both = page.evaluate(
                        """() => {
                            const tabs = Array.from(document.querySelectorAll('[role="tab"]'));
                            const relevant = tabs.filter(t => /\b(email|mobile)\b/i.test(t.textContent || ''));
                            if (relevant.length < 2) return false;
                            const actions = ['send otp','send sms','verify','login','sign in'];
                            for (const t of relevant) {
                                let parent = t.closest('div, form, section') || document.body;
                                const inputs = parent.querySelectorAll('input[placeholder*="mobile" i], input[placeholder*="email" i], input[name*="mobile" i], input[name*="email" i], input[type="email"]');
                                if (inputs.length === 0) continue;
                                const buttons = Array.from(parent.querySelectorAll('button, a')).filter(el => {
                                    const txt = (el.textContent || '').toLowerCase();
                                    return actions.some(a => txt.indexOf(a) !== -1);
                                });
                                if (buttons.length > 0) return true;
                            }
                            return false;
                        }"""
                    )
                    if parent_has_both:
                        return True
                except Exception:
                    pass
        except Exception:
            pass

    except Exception:
        pass
    return False


# ── Navigation Discovery ─────────────────────────────────────────

def _discover_nav_links(page):
    """Find all navigation links on the current page."""
    nav_links = {}
    nav_selectors = [
        "nav a", ".sidebar a", ".nav-link", ".menu a", "[role='navigation'] a",
        "a[href*='dashboard']", "a[href*='report']", "a[href*='fleet']",
        "a[href*='monitor']", "a[href*='summary']", "a[href*='vehicle']",
        ".tab a", "[role='tab']",
        # Angular SPA sidebar items
        ".sidebar-nav a", ".side-menu a", "[class*='sidebar'] a",
        "[class*='nav-menu'] a", "[class*='sidenav'] a",
    ]

    for sel in nav_selectors:
        try:
            links = page.locator(sel)
            for i in range(links.count()):
                link = links.nth(i)
                if not link.is_visible():
                    continue
                text = link.text_content().strip().lower()
                href = link.get_attribute("href") or ""
                # Allow hash routes (#/path) but skip bare anchors (#) and javascript:
                if text and href and href != "#" and not href.startswith("javascript"):
                    page_name = re.sub(r'[^a-z0-9]+', '_', text).strip('_')
                    if page_name and page_name not in nav_links and len(page_name) > 1:
                        # Build full URL: handle hash routes (#/) and relative paths
                        if href.startswith("http"):
                            full_url = href
                        elif href.startswith("#"):
                            # Angular hash route — prepend base URL
                            base = page.url.split("#")[0]
                            full_url = base + href
                        else:
                            full_url = ""
                        nav_links[page_name] = {
                            "url": full_url,
                            "nav_selector": sel + f':has-text("{link.text_content().strip()}")',
                            "text": link.text_content().strip(),
                        }
        except Exception:
            continue

    return nav_links


# ── Sub-page / deep-crawl helpers ───────────────────────────────

def _url_to_page_name(url: str) -> str:
    """Derive a stable page-map key from a URL hash path."""
    try:
        path = url.split("#/", 1)[1] if "#/" in url else url.split("/")[-1]
        name = re.sub(r"[^a-z0-9/]+", "_", path.lower()).strip("_/").replace("/", "_")
        return name[:80] or "page"
    except Exception:
        return "page"


def _expand_sidebar_accordions(page, budget_ms: int = 12000):
    """
    Expand all collapsed sidebar accordions in a single JS evaluate call.
    Much faster than iterating Playwright locators.
    """
    snapshot_url = page.url
    try:
        page.evaluate("""() => {
            const sels = [
                "[class*='sidebar'] a[aria-expanded='false']",
                "[class*='sidenav'] a[aria-expanded='false']",
                "[class*='sidebar'] li > a[href='#']",
                "li.has-sub > a:not([href^='#/'])",
                "li.has-arrow > a:not([href^='#/'])",
                "a[data-toggle='collapse'][aria-expanded='false']",
                "a[data-bs-toggle='collapse'][aria-expanded='false']"
            ];
            const clicked = new Set();
            for (const sel of sels) {
                try {
                    document.querySelectorAll(sel).forEach(el => {
                        if (!clicked.has(el) && el.offsetParent !== null) {
                            clicked.add(el);
                            try { el.click(); } catch(e) {}
                        }
                    });
                } catch(e) {}
            }
        }""")
        # Wait briefly for Angular animations to settle
        try:
            page.wait_for_function(
                "() => !document.querySelector('.collapsing')",
                timeout=3000,
            )
        except Exception:
            pass
    except Exception:
        pass
    # If JS click navigated away, return to sidebar page
    if page.url != snapshot_url:
        try:
            page.goto(snapshot_url, wait_until="domcontentloaded")
        except Exception:
            pass


def _set_date_range(page):
    """
    If the current page has a date-range picker, set it to the last 30 days
    so that report/trip pages return real data.  Silently skips pages that
    have no date picker.
    """
    today = datetime.now()
    start = today - timedelta(days=30)

    fmt_pairs = [
        ("%d/%m/%Y", "%d/%m/%Y"),   # Indian default  08/04/2026
        ("%m/%d/%Y", "%m/%d/%Y"),   # US
        ("%Y-%m-%d", "%Y-%m-%d"),   # ISO
        ("%d-%m-%Y", "%d-%m-%Y"),
    ]
    start_sels = [
        "input[placeholder*='From' i]",
        "input[placeholder*='Start' i]",
        "input[placeholder*='Begin' i]",
        "input[type='date']:first-of-type",
        ".date-from input",
        ".start-date input",
        "app-date-range input:first-of-type",
        "ngx-daterangepicker-material input:first-of-type",
        "mat-date-range-input input:first-of-type",
    ]
    end_sels = [
        "input[placeholder*='To' i]",
        "input[placeholder*='End' i]",
        "input[type='date']:last-of-type",
        ".date-to input",
        ".end-date input",
        "app-date-range input:last-of-type",
        "ngx-daterangepicker-material input:last-of-type",
        "mat-date-range-input input:last-of-type",
    ]

    filled = False
    for start_sel in start_sels:
        try:
            inp = page.locator(start_sel).first
            if not inp.is_visible(timeout=300):
                continue
            for sfmt, _ in fmt_pairs:
                try:
                    inp.fill(start.strftime(sfmt))
                    filled = True
                    break
                except Exception:
                    continue
            if filled:
                break
        except Exception:
            continue

    if not filled:
        return  # No date picker on this page

    for end_sel in end_sels:
        try:
            inp = page.locator(end_sel).first
            if not inp.is_visible(timeout=300):
                continue
            for _, efmt in fmt_pairs:
                try:
                    inp.fill(today.strftime(efmt))
                    break
                except Exception:
                    continue
            break
        except Exception:
            continue

    # Trigger search/apply
    apply_sels = [
        "button:has-text('Apply')",
        "button:has-text('Search')",
        "button:has-text('Go')",
        "button:has-text('Submit')",
        "button:has-text('Filter')",
        "[class*='apply-btn']",
        "[class*='search-btn']",
        "button[type='submit']",
    ]
    for sel in apply_sels:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=300):
                btn.click()
                _wait_for_page_ready(page)
                _wait_for_api_data(page, timeout=8000)
                break
        except Exception:
            continue


def _close_any_overlay(page):
    """Press Escape and try close buttons to dismiss any open modal or dropdown."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass
    try:
        for close_sel in [
            "[role='dialog'] button[aria-label='Close']",
            "[role='dialog'] .close",
            "[role='dialog'] .btn-close",
            ".modal-header .close",
            "button.close",
        ]:
            btn = page.locator(close_sel).first
            if btn.is_visible(timeout=200):
                btn.click()
                page.wait_for_timeout(300)
                break
    except Exception:
        pass


def _extract_modal_elements(page, pname, elements, shared_selectors):
    """
    If a modal/dialog is currently visible, extract its title and table headers.
    Returns True if a modal was found.
    """
    modal_sels = [
        "[role='dialog']",
        ".modal.show .modal-content",
        "ngb-modal-window",
        "bs-modal",
        ".mat-dialog-container",
        "app-modal",
    ]
    for ms in modal_sels:
        try:
            modal = page.locator(ms).first
            if not modal.is_visible(timeout=400):
                continue
            # Title
            for title_sel in [".modal-title", "h4", "h5", ".mat-dialog-title", "h3"]:
                try:
                    t = modal.locator(title_sel).first
                    if t.is_visible(timeout=200):
                        txt = (t.text_content() or "").strip()
                        if txt and 2 <= len(txt) <= 80:
                            sel_key = f'{ms} {title_sel}:has-text("{txt.replace(chr(34), chr(39))}")'
                            if sel_key not in shared_selectors:
                                shared_selectors.add(sel_key)
                                elements.append({
                                    "label": txt,
                                    "selector": sel_key,
                                    "backup_selector": "",
                                    "element_type": "modal_heading",
                                    "section": "modal",
                                    "is_dynamic": False,
                                    "value_sample": txt,
                                    "text_anchor_label": txt,
                                    "opens_modal": True,
                                })
                except Exception:
                    pass
            # Table headers inside modal
            try:
                ths = modal.locator("th")
                for i in range(min(ths.count(), 20)):
                    th = ths.nth(i)
                    txt = (th.text_content() or "").strip()
                    if txt and 2 <= len(txt) <= 80:
                        sel_key = f'{ms} th:has-text("{txt.replace(chr(34), chr(39))}")'
                        if sel_key not in shared_selectors:
                            shared_selectors.add(sel_key)
                            elements.append({
                                "label": f"Modal Column: {txt}",
                                "selector": sel_key,
                                "backup_selector": "",
                                "element_type": "modal_table_header",
                                "section": "modal",
                                "is_dynamic": False,
                                "value_sample": txt,
                                "text_anchor_label": txt,
                                "opens_modal": True,
                            })
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def _extract_dropdown_options(page, pname, elements, shared_selectors):
    """
    If a dropdown/context-menu is currently visible, extract its option labels.
    Returns True if a dropdown was found.
    """
    dd_sels = [
        ".dropdown-menu.show",
        ".mat-menu-panel .mat-menu-content",
        ".cdk-overlay-pane .mat-menu-content",
        "[class*='dropdown-menu']:not([style*='display: none'])",
        "[class*='context-menu']:not([style*='display: none'])",
    ]
    for ds in dd_sels:
        try:
            dd = page.locator(ds).first
            if not dd.is_visible(timeout=400):
                continue
            for isel in ["[role='menuitem']", ".mat-menu-item", ".dropdown-item", "li", "button", "a"]:
                try:
                    opts = dd.locator(isel)
                    found = 0
                    for i in range(min(opts.count(), 15)):
                        opt = opts.nth(i)
                        txt = (opt.text_content() or "").strip()
                        if txt and 2 <= len(txt) <= 60:
                            sel_key = f'{ds} {isel}:has-text("{txt.replace(chr(34), chr(39))}")'
                            if sel_key not in shared_selectors:
                                shared_selectors.add(sel_key)
                                elements.append({
                                    "label": txt,
                                    "selector": sel_key,
                                    "backup_selector": "",
                                    "element_type": "dropdown_option",
                                    "section": "action_menu",
                                    "is_dynamic": False,
                                    "value_sample": txt,
                                    "text_anchor_label": txt,
                                })
                                found += 1
                    if found > 0:
                        return True
                except Exception:
                    pass
        except Exception:
            continue
    return False


def _extract_click_interactions(page, pname, elements, shared_selectors,
                                crawl_queue, visited_urls, depth, current_url):
    """
    Probe clickable elements that reveal content or trigger navigation:
      1. Status/count cards   → URL changes    → queue new page in BFS
      2. Table row View links → modal appears  → extract title + column headers
      3. Kebab/three-dot btns → dropdown opens → extract option labels
    Only probes first visible instance for modals/dropdowns (all rows have
    the same structure). Skips destructive actions. Always recovers.
    """
    SKIP_TEXTS = {"delete", "remove", "logout", "sign out", "reset", "clear all", "deactivate"}

    def _safe_back():
        """Navigate back to current_url if we drifted."""
        try:
            exp = current_url.split("#", 1)[1] if "#" in current_url else ""
            cur = page.url.split("#", 1)[1] if "#" in page.url else ""
            if exp and cur != exp:
                page.goto(current_url, wait_until="domcontentloaded", timeout=15000)
                _wait_for_spinners_gone(page)
                page.wait_for_timeout(400)
        except Exception:
            pass

    # ── 1. Status / count nav-cards ──────────────────────────────────
    # These cards either: (a) navigate to a new URL → queue as BFS page,
    # or (b) filter a table in-place (URL stays same) → extract the filtered view.
    nav_card_sels = [
        "div.status-card",
        "div.vehicle-count-box",
        "div.count-box",
        ".summary-card",
        "[class*='count-card']",
        "[class*='status-item']",
    ]
    seen_nav_urls: set = set()
    seen_card_labels: set = set()  # dedup across selectors
    for sel in nav_card_sels:
        try:
            cards = page.locator(sel)
            n = min(cards.count(), 20)
            for i in range(n):
                card = cards.nth(i)
                try:
                    if not card.is_visible(timeout=300):
                        continue
                except Exception:
                    continue
                label = (card.text_content() or "").strip()
                if any(s in label.lower() for s in SKIP_TEXTS):
                    continue
                # Normalise label for dedup (strip whitespace/numbers)
                import re as _re
                label_key = _re.sub(r"\d", "", label).strip().lower()
                if label_key in seen_card_labels:
                    continue
                seen_card_labels.add(label_key)

                url_pre = page.url
                try:
                    card.evaluate("el => el.click()")
                except Exception:
                    try:
                        card.dispatch_event("click")
                    except Exception:
                        continue

                # Poll for URL change up to 1.5 s
                url_post = url_pre
                for _ in range(15):
                    page.wait_for_timeout(100)
                    url_post = page.url
                    if url_post != url_pre:
                        break

                if url_post != url_pre and "/auth/" not in url_post:
                    # True navigation — queue as new BFS page
                    if url_post not in visited_urls and url_post not in seen_nav_urls:
                        seen_nav_urls.add(url_post)
                        visited_urls.add(url_post)
                        crawl_queue.append((url_post, _url_to_page_name(url_post), "", depth + 1))
                    _safe_back()
                    page.wait_for_timeout(400)
                else:
                    # In-place filter — extract table headers/columns from filtered view
                    page.wait_for_timeout(600)
                    _wait_for_spinners_gone(page)
                    # Table column headers
                    th_els = page.locator("table thead th, table thead td")
                    th_count = th_els.count()
                    if th_count > 0:
                        col_labels = []
                        for j in range(min(th_count, 15)):
                            try:
                                col_txt = (th_els.nth(j).text_content() or "").strip()
                                if col_txt:
                                    col_labels.append(col_txt)
                            except Exception:
                                pass
                        if col_labels:
                            fkey = f"filter:{label_key}"
                            if fkey not in shared_selectors:
                                shared_selectors.add(fkey)
                                elements.append({
                                    "element_type": "filter_view",
                                    "label": f"{label} → Columns: {', '.join(col_labels)}",
                                    "selector": sel,
                                    "value": label,
                                    "interactable": True,
                                })
                    # Sample first data row cells
                    row1 = page.locator("table tbody tr").first
                    try:
                        if row1.is_visible(timeout=300):
                            cells = row1.locator("td")
                            cell_count = cells.count()
                            if cell_count > 0:
                                sample_vals = []
                                for j in range(min(cell_count, 6)):
                                    try:
                                        cv = (cells.nth(j).text_content() or "").strip()
                                        if cv:
                                            sample_vals.append(cv)
                                    except Exception:
                                        pass
                                if sample_vals:
                                    skey = f"filter_row:{label_key}"
                                    if skey not in shared_selectors:
                                        shared_selectors.add(skey)
                                        elements.append({
                                            "element_type": "filter_view_row",
                                            "label": f"{label} → Sample row: {' | '.join(sample_vals)}",
                                            "selector": "table tbody tr:first-child td",
                                            "value": label,
                                            "interactable": False,
                                        })
                    except Exception:
                        pass
                    _close_any_overlay(page)
        except Exception:
            _safe_back()

    # ── 2. Table row "View"-style links → modal ───────────────────────
    view_sels = [
        "td a:has-text('View')",
        "td button:has-text('View')",
        "td a:has-text('Details')",
        "td a:has-text('Show')",
    ]
    modal_probed = False
    for sel in view_sels:
        if modal_probed:
            break
        try:
            items = page.locator(sel)
            if items.count() == 0:
                continue
            item = items.first
            if not item.is_visible(timeout=300):
                continue
            label = (item.text_content() or "").strip()
            if any(s in label.lower() for s in SKIP_TEXTS):
                continue
            url_pre = page.url
            item.dispatch_event("click")
            page.wait_for_timeout(700)
            if page.url != url_pre:
                _safe_back()
            else:
                if _extract_modal_elements(page, pname, elements, shared_selectors):
                    modal_probed = True
                _close_any_overlay(page)
                page.wait_for_timeout(300)
        except Exception:
            _safe_back()

    # ── 3. Kebab / three-dot menus → dropdown options ─────────────────
    kebab_sels = [
        "td button:has(.fa-ellipsis-v)",
        "td button:has([class*='ellipsis'])",
        "td [class*='kebab']",
        "td [class*='more-action']",
        ".action-col button",
        "td:last-child > button",
        "table tbody tr:first-child td:last-child button",
    ]
    dropdown_probed = False
    for sel in kebab_sels:
        if dropdown_probed:
            break
        try:
            items = page.locator(sel)
            if items.count() == 0:
                continue
            item = items.first
            if not item.is_visible(timeout=300):
                continue
            url_pre = page.url
            item.dispatch_event("click")
            page.wait_for_timeout(600)
            if page.url != url_pre:
                _safe_back()
            else:
                if _extract_dropdown_options(page, pname, elements, shared_selectors):
                    dropdown_probed = True
                _close_any_overlay(page)
                page.wait_for_timeout(300)
        except Exception:
            _safe_back()


def _select_first_vehicle(page) -> bool:
    """
    If the current page has a 'Select Vehicle' multi-select dropdown,
    open it and pick the first available vehicle so that data loads.
    Returns True if a vehicle was selected, False otherwise.
    """
    try:
        # ng-select whose placeholder text contains "Vehicle"
        container = (
            page.locator("ng-select")
            .filter(has=page.locator(".ng-placeholder:has-text('Vehicle')"))
            .first
        )
        if not container.is_visible(timeout=800):
            return False
        # Click the select box to open the dropdown
        container.locator(".ng-select-container").click(timeout=2000)
        page.wait_for_timeout(600)
        # Pick the first option in the dropdown panel
        opt = page.locator("ng-dropdown-panel .ng-option").first
        if opt.is_visible(timeout=1500):
            opt.click(timeout=2000)
            page.wait_for_timeout(400)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return False


def _discover_report_cards(page, reports_url: str) -> list:
    """
    On the Reports landing page (#/pages/reports-new), click each visible
    card to discover the sub-page URL it navigates to.  Navigates back to
    `reports_url` after each card click.
    Returns list of {url, name} dicts for BFS queuing.
    """
    results = []
    seen_urls: set = set()

    # The reports page renders cards as div.widget-title elements.
    # Clicking each card navigates to a sub-URL like #/pages/reports-new/vehiclestatus.
    card_sels = [
        "div.widget-title",
        "[class*='widget-title']",
        "app-report-card",
        "[class*='report-card']",
        "mat-grid-tile",
    ]

    # Collect all unique visible card texts first (avoid stale locator issues)
    card_texts: list = []
    seen_texts: set = set()
    for sel in card_sels:
        try:
            locs = page.locator(sel)
            cnt = locs.count()
            if cnt == 0:
                continue
            for i in range(min(cnt, 50)):
                try:
                    el = locs.nth(i)
                    if not el.is_visible(timeout=300):
                        continue
                    txt = (el.text_content() or "").strip().split("\n")[0][:50].strip()
                    if txt and txt not in seen_texts:
                        seen_texts.add(txt)
                        card_texts.append((txt, sel))
                except Exception:
                    continue
            if card_texts:
                break  # First selector that yields visible cards wins
        except Exception:
            continue

    if not card_texts:
        return results

    for card_text, card_sel in card_texts:
        try:
            # Re-locate the card by text (stale-safe)
            card = page.locator(card_sel).filter(has_text=card_text).first
            if not card.is_visible(timeout=500):
                continue

            card.scroll_into_view_if_needed()
            card.click()
            page.wait_for_timeout(1200)
            new_url = page.url
            if (
                new_url != reports_url
                and "reports" in new_url
                and new_url not in seen_urls
            ):
                seen_urls.add(new_url)
                results.append({"url": new_url, "name": _url_to_page_name(new_url)})

            # Navigate back to reports landing
            page.goto(reports_url, wait_until="domcontentloaded", timeout=15000)
            _wait_for_spinners_gone(page)
            page.wait_for_timeout(600)
        except Exception:
            # Recover back to reports page
            try:
                if page.url != reports_url:
                    page.goto(reports_url, wait_until="domcontentloaded", timeout=12000)
                    _wait_for_spinners_gone(page)
            except Exception:
                pass

    return results


def _discover_sub_links(page, base_url: str, visited_urls: set) -> list:
    """
    Scan the current page for all internal hash-route links that have not yet
    been visited.  Captures both <a href="#/..."> anchors and Angular
    [routerLink] attributes on non-anchor elements.
    Returns a list of dicts: {url, name, nav_selector}.
    """
    base = base_url.split("#")[0]
    results = []
    seen_in_call: set = set()

    # ── href-based anchors ──────────────────────────────────────
    try:
        anchors = page.locator("a[href^='#/']")
        for i in range(min(anchors.count(), 400)):
            try:
                a = anchors.nth(i)
                href = (a.get_attribute("href") or "").strip()
                if not href or not href.startswith("#/"):
                    continue
                # Skip auth routes
                if any(x in href for x in ["/auth/", "/login", "/register"]):
                    continue
                full_url = base + href
                if full_url in visited_urls or full_url in seen_in_call:
                    continue
                seen_in_call.add(full_url)
                results.append({
                    "url": full_url,
                    "name": _url_to_page_name(full_url),
                    "nav_selector": f'a[href="{href}"]',
                })
            except Exception:
                continue
    except Exception:
        pass

    # ── Angular [routerLink] on non-anchor elements ─────────────
    try:
        rl_els = page.locator("[routerlink]:not(a), [ng-reflect-router-link]:not(a)")
        for i in range(min(rl_els.count(), 300)):
            try:
                el = rl_els.nth(i)
                rl = (
                    el.get_attribute("routerLink")
                    or el.get_attribute("routerlink")
                    or el.get_attribute("ng-reflect-router-link")
                    or ""
                ).strip()
                if not rl or rl in (".", "/"):
                    continue
                if any(x in rl for x in ["/auth/", "/login"]):
                    continue
                full_url = base + "#" + rl if rl.startswith("/") else base + rl
                if full_url in visited_urls or full_url in seen_in_call:
                    continue
                seen_in_call.add(full_url)
                rl_esc = rl.replace('"', "'")
                results.append({
                    "url": full_url,
                    "name": _url_to_page_name(full_url),
                    "nav_selector": f'[routerLink="{rl_esc}"]',
                })
            except Exception:
                continue
    except Exception:
        pass

    return results


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

def crawl_site(site_name: str, progress_callback=None, jhs_credentials=None):
    """
    Crawl a site end-to-end:
      1. Login
      2. Discover navigation
      3. Visit each page and extract elements
      4. Save site-map.json
      5. Seed site_elements table

    Parameters
    ----------
    site_name : str
        One of jhs81, jhs82, jhs83, jhs84
    progress_callback : callable, optional
        Receives (percent: int, message: str)

    Returns
    -------
    dict with crawl summary
    """

    def _progress(pct, msg):
        if progress_callback:
            progress_callback(pct, msg)

    log_event(
        "crawler_start",
        site=site_name,
    )
    crawl_start = time.time()
    env = _site_env(site_name, jhs_credentials=jhs_credentials)
    if not env["url"]:
        log_event(
            "crawler_error",
            site=site_name,
            error_type="ValueError",
            error_message=f"No URL configured for {site_name}",
        )
        raise ValueError(f"No URL configured for {site_name}. Check .env file.")

    _progress(5, "Launching browser…")

    os.makedirs("screenshots", exist_ok=True)

    site_map = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "crawled_from": site_name,
        "login": {},
        "pages": {},
    }

    total_elements = 0

    with sync_playwright() as pw:
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
        browser = pw.chromium.launch(headless=headless)
        
        state_file = "captures/jhs_state.json"
        if os.path.exists(state_file):
            print(f"[CRAWLER] Loading JHS storage state from {state_file}...", flush=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080}, storage_state=state_file)
        else:
            print("[CRAWLER] No JHS storage state file found. Starting fresh context.", flush=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # ── Step 1: Login ───────────────────────────────
        _progress(10, "Logging in…")
        login_info = {}
        _perform_login(page, env, login_info)
        site_map["login"] = login_info
        _progress(25, "Login successful")

        # ── Step 2: Expand sidebar menus & discover all navigation ──────
        _progress(30, "Expanding sidebar accordion menus…")
        _wait_for_page_ready(page)
        _expand_sidebar_accordions(page)
        try:
            page.wait_for_function(
                """() => {
                    const links = document.querySelectorAll(
                        'nav a, .sidebar a, [class*="sidebar"] a, [class*="sidenav"] a'
                    );
                    return links.length >= 3;
                }""",
                timeout=8000,
            )
        except Exception:
            pass
        nav_links = _discover_nav_links(page)
        current_url = page.url

        # ── BFS queue: (url, page_name, nav_selector, depth) ────────────
        visited_urls: set = set()
        crawl_queue: deque = deque()

        visited_urls.add(current_url)
        crawl_queue.append((current_url, "dashboard", "", 0))
        for pname, pinfo in nav_links.items():
            purl = pinfo.get("url", "")
            if purl and purl.startswith("http") and purl not in visited_urls:
                visited_urls.add(purl)
                crawl_queue.append((purl, pname, pinfo.get("nav_selector", ""), 0))

        MAX_PAGES = 200   # safety cap (150 base + up to 35 report sub-pages + buffer)
        MAX_DEPTH = 3     # dashboard=0, detail=1, sub-detail=2, deep=3
        _progress(35, f"Queued {len(crawl_queue)} initial pages — starting BFS crawl…")

        # Re-login tracking: allow a small number of automatic re-login attempts
        relogin_attempts = 0
        MAX_RELOGIN = int(os.getenv("CRAWL_MAX_RELOGIN", 2))

        # ── Step 3: BFS page crawl ───────────────────────────────────────
        page_count = 0
        while crawl_queue and page_count < MAX_PAGES:
            url, pname, nav_sel, depth = crawl_queue.popleft()
            page_count += 1
            pct = min(40 + int((page_count / MAX_PAGES) * 50), 90)
            _progress(pct, f"[{page_count}/{MAX_PAGES}] {pname}  (depth {depth})")

            # ── Navigate ──────────────────────────────────────────
            # Strategy: click the nav link if available (works with Angular router),
            # fall back to URL navigation for sub-pages that have no nav selector.
            nav_ok = False
            if nav_sel:
                try:
                    nav_loc = page.locator(nav_sel).first
                    if nav_loc.is_visible(timeout=2000):
                        nav_loc.dispatch_event("click")
                        page.wait_for_timeout(800)
                        nav_ok = True
                except Exception:
                    pass

            if not nav_ok:
                try:
                    # Use full page.goto for sub-pages / first load
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception as exc:
                    _progress(pct, f"  ✗ Navigation failed: {exc}")
                    site_map["pages"][pname] = {
                        "url": url, "nav_selector": nav_sel,
                        "loading_indicators": [], "api_endpoints": [],
                        "elements": [], "error": str(exc),
                    }
                    continue

            # Confirm navigation reached the right route
            try:
                hash_part = url.split("#", 1)[1] if "#" in url else ""
                if hash_part and hash_part not in page.url:
                    # Nav click took us to the wrong place — force URL
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                pass

            # Detect login page and attempt re-login if necessary (do not
            # immediately abort; allow a limited number of automatic tries).
            try:
                redirected_to_auth = any(x in page.url for x in ["/auth/login", "#/auth/"])
            except Exception:
                redirected_to_auth = False

            if redirected_to_auth or _is_login_page(page):
                if relogin_attempts >= MAX_RELOGIN:
                    _progress(pct, "  ✗ Redirected to login — session expired, stopping")
                    break
                relogin_attempts += 1
                _progress(pct, f"  ↻ Detected login page — attempting re-login ({relogin_attempts}/{MAX_RELOGIN})")
                try:
                    _perform_login(page, env, login_info)
                    # After login, attempt to reach the intended URL again
                    try:
                        if nav_sel:
                            try:
                                nav_loc = page.locator(nav_sel).first
                                if nav_loc.is_visible(timeout=2000):
                                    nav_loc.dispatch_event("click")
                                    page.wait_for_timeout(800)
                                    nav_ok = True
                            except Exception:
                                pass
                        if not nav_ok:
                            page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    except Exception:
                        pass
                except Exception as exc:
                    _progress(pct, f"  ✗ Re-login attempt failed: {exc}")
                    break

            _wait_for_page_ready(page)

            # On report sub-pages (not the landing card grid), select a vehicle
            # first so the date-range filter actually returns data.
            _is_report_subpage = (
                "reports-new" in page.url
                and page.url.rstrip("/") != url.split("#")[0].rstrip("/") + "#/pages/reports-new"
            )
            if _is_report_subpage:
                _select_first_vehicle(page)

            # Set date range on report/trip/insight pages so data loads
            _set_date_range(page)

            # Wait for Angular HTTP calls to populate metric values
            _wait_for_api_data(page)

            # ── Extract elements (shared dedup across initial + all tabs) ──
            shared_selectors: set = set()
            elements: list = []
            _extract_elements(page, pname, elements, shared_selectors)

            # Click every tab and re-extract
            tabs = _discover_tabs(page)
            for tab_label, tab_sel in tabs:
                try:
                    tab_loc = page.locator(tab_sel).first
                    # Use JS dispatch_event to bypass pointer-intercepting containers
                    try:
                        tab_loc.dispatch_event("click", timeout=5000)
                    except Exception:
                        page.evaluate("el => el.click()", tab_loc.element_handle(timeout=3000))
                    _wait_for_page_ready(page)
                    _wait_for_api_data(page)
                    _extract_elements(page, pname, elements, shared_selectors)
                    _progress(pct, f"  ↳ Tab '{tab_label}': {len(elements)} elements total")
                except Exception as te:
                    print(f"[WARN] Tab '{tab_label}' on '{pname}' skipped: {te}")

            # ── Probe click interactions: nav cards, modals, dropdowns ──
            if depth < MAX_DEPTH:
                _extract_click_interactions(
                    page, pname, elements, shared_selectors,
                    crawl_queue, visited_urls, depth, url,
                )
                # Safety belt — restore page if drift occurred
                try:
                    exp_hash = url.split("#", 1)[1] if "#" in url else ""
                    cur_hash = page.url.split("#", 1)[1] if "#" in page.url else ""
                    if exp_hash and cur_hash != exp_hash:
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        _wait_for_spinners_gone(page)
                except Exception:
                    pass

            elements = _detect_dynamic(page, elements)

            # Loading indicators present on this page
            loading_sels = []
            for lsel in [".spinner", ".loading", "[class*='spinner']", ".skeleton"]:
                try:
                    if page.locator(lsel).count() > 0:
                        loading_sels.append(lsel)
                except Exception:
                    pass

            # Unique page key — collision-safe
            page_key = pname
            suffix = 2
            while page_key in site_map["pages"]:
                page_key = f"{pname}_{suffix}"
                suffix += 1

            site_map["pages"][page_key] = {
                "url": page.url,
                "nav_selector": nav_sel,
                "loading_indicators": loading_sels,
                "api_endpoints": _capture_api_endpoints([]),
                "elements": elements,
            }
            total_elements += len(elements)

            # ── Reports landing page: discover card sub-pages ──────
            # The report cards use click-handlers (no routerLink), so we
            # click each card to find its URL, then navigate back.
            # Trigger only on the landing page (not sub-pages like /vehiclestatus)
            _is_reports_landing = (
                "reports-new" in url
                and not re.search(r"reports-new/.+", url)
            )
            if depth < MAX_DEPTH and _is_reports_landing:
                report_cards = _discover_report_cards(page, url)
                rc_queued = 0
                for rc in report_cards:
                    if rc["url"] not in visited_urls:
                        visited_urls.add(rc["url"])
                        crawl_queue.append((rc["url"], rc["name"], "", depth + 1))
                        rc_queued += 1
                if rc_queued:
                    _progress(pct, f"  ↳ Discovered {rc_queued} report card sub-pages")

            # ── Discover sub-pages for deeper BFS ─────────────────
            if depth < MAX_DEPTH:
                sub_links = _discover_sub_links(page, url, visited_urls)
                queued = 0
                for sl in sub_links:
                    if sl["url"] not in visited_urls:
                        visited_urls.add(sl["url"])
                        crawl_queue.append((
                            sl["url"],
                            _url_to_page_name(sl["url"]),
                            sl.get("nav_selector", ""),
                            depth + 1,
                        ))
                        queued += 1
                if queued:
                    _progress(pct, f"  ↳ Queued {queued} sub-pages from {pname}")

        browser.close()

    # ── Step 4: Save site-map.json ──────────────────────
    _progress(92, "Saving site-map.json…")
    map_path = os.getenv("SITE_MAP_PATH", "site-map.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(site_map, f, indent=2, default=str)
    print("\nExtraction summary:")
    for pname, pdata in site_map.get("pages", {}).items():
        count = len(pdata.get("elements", []))
        display_name = pname.replace("_", " ").title()
        if count == 0:
            print(f"  {display_name}: {count} elements ← WARNING: no elements found, check selectors")
        else:
            print(f"  {display_name}: {count} elements")
    # ── Step 5: Seed site_elements table ────────────────
    _progress(95, "Seeding database…")

    # Clear previous elements (shared map — no site_id)
    SiteElement.query.delete()

    now = datetime.now(timezone.utc)
    for pname, pdata in site_map.get("pages", {}).items():
        for el in pdata.get("elements", []):
            db.session.add(SiteElement(
                page=pname,
                section=el.get("section", "")[:100],
                label=el.get("label", "")[:255],
                selector=el.get("selector", "")[:500],
                element_type=el.get("element_type", "")[:50],
                is_dynamic=el.get("is_dynamic", False),
                value_sample=el.get("value_sample", "")[:500],
                last_crawled_at=now,
            ))

    db.session.commit()
    _progress(100, "Crawl complete")

    crawl_duration = int((time.time() - crawl_start) * 1000)
    log_event(
        "crawler_success",
        site=site_name,
        duration_ms=crawl_duration,
        pages_crawled=len(site_map["pages"]),
        elements_found=total_elements,
    )
    return {
        "site": site_name,
        "pages_crawled": len(site_map["pages"]),
        "elements_found": total_elements,
        "site_map_path": map_path,
    }
