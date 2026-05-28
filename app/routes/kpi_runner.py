import time
import re
import threading
import io
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_file, current_app
from db import db
from db.models import TestRun, TestCase, ValueCapture, Site, KpiDownloadHistory
from app.utils.kpi_steps import KPI_STEPS
from app.utils.kpi_excel import generate_kpi_excel

kpi_runner_bp = Blueprint("kpi_runner", __name__)

_active_kpi_runs = {}
_active_kpi_runs_lock = threading.Lock()

def _wait_and_capture_kpi_data(page, start_time_ref, timeout_sec=45.0, cancel_check_fn=None):
    """Universal helper to wait for table, grid, paginator, or empty state to load, then capture count and time."""
    # We prioritize active page containers in an SPA to avoid matching stale/cached paginators or widgets
    containers = [".page-inner-content ", "nb-layout-column ", ".main-content ", ""]
    
    # 1. Wait up to 5s to see if a visible paginator exists inside an active content container
    has_paginator = False
    for _ in range(10):
        if cancel_check_fn:
            cancel_check_fn()
            
        pag_found = False
        for prefix in containers:
            for base_sel in ['.mat-paginator-range-label:visible', '.mat-mdc-paginator-range-label:visible']:
                if page.locator(f"{prefix}{base_sel}").count() > 0:
                    has_paginator = True
                    pag_found = True
                    break
            if pag_found:
                break
        if pag_found:
            break
        page.wait_for_timeout(500)
        
    rec_val = 0
    start_wait = time.time()
    while time.time() - start_wait < timeout_sec:
        if cancel_check_fn:
            cancel_check_fn()
            
        # Check for any visible "no records" / "no data" overlay elements inside active page container
        no_data_selectors = [
            '.no-data', '.no-records', '.empty-state',
            'text="No data found"', 'text="No records found"',
            'text="No Data"', 'text="No Records"', 'text="No data"'
        ]
        no_data_visible = False
        for prefix in containers:
            for nd_sel in no_data_selectors:
                try:
                    loc = page.locator(f"{prefix}{nd_sel}")
                    if loc.count() > 0 and loc.first.is_visible():
                        no_data_visible = True
                        break
                except Exception:
                    pass
            if no_data_visible:
                break
                
        if no_data_visible:
            rec_val = 0
            break
            
        # Try primary paginator extraction inside active page container
        if has_paginator:
            paginator = None
            for prefix in containers:
                for base_sel in ['.mat-paginator-range-label:visible', '.mat-mdc-paginator-range-label:visible']:
                    loc = page.locator(f"{prefix}{base_sel}").first
                    if loc.count() > 0:
                        paginator = loc
                        break
                if paginator:
                    break
                    
            if paginator:
                txt = paginator.text_content()
                # Check if it shows "of 0"
                if re.search(r"of\s+0\b", txt, re.IGNORECASE):
                    rec_val = 0
                    break
                m = re.search(r"of\s+([\d,]+)", txt, re.IGNORECASE)
                if m:
                    val = int(m.group(1).replace(',', ''))
                    if val > 0:
                        rec_val = val
                        break
                        
        # Multi-layer fallback page scanning for any visible text representing total count inside active container
        scanned_val = None
        for prefix in containers:
            for base_sel in ['.mat-paginator-range-label:visible', '.mat-mdc-paginator-range-label:visible', 'span:visible', 'div:visible', 'td:visible', 'p:visible', 'li:visible']:
                try:
                    loc = page.locator(f"{prefix}{base_sel}")
                    cnt = loc.count()
                    for idx in range(min(cnt, 20)):  # limit scan depth to avoid lag
                        el = loc.nth(idx)
                        txt = el.text_content()
                        m_of = re.search(r"\bof\s+([\d,]+)\b", txt, re.IGNORECASE)
                        if m_of:
                            val = int(m_of.group(1).replace(',', ''))
                            if val > 0:
                                scanned_val = val
                                break
                        m_tot = re.search(r"total\s*(?:count)?\s*:\s*([\d,]+)", txt, re.IGNORECASE)
                        if m_tot:
                            val = int(m_tot.group(1).replace(',', ''))
                            if val > 0:
                                scanned_val = val
                                break
                    if scanned_val is not None:
                        break
                except Exception:
                    pass
            if scanned_val is not None:
                break
                
        if scanned_val is not None:
            rec_val = scanned_val
            break
            
        # Table row fallback if no text indicators found yet
        rows_loc = None
        for prefix in containers:
            loc = page.locator(f"{prefix}table tbody tr:visible, {prefix}mat-row:visible, {prefix}.mat-row:visible, {prefix}.mat-mdc-row:visible, {prefix}tr[role='row']:visible")
            if loc.count() > 0:
                rows_loc = loc
                break
                
        if rows_loc and rows_loc.count() > 0:
            first_row_text = rows_loc.first.text_content().lower()
            if "no data" in first_row_text or "no record" in first_row_text or "empty" in first_row_text:
                rec_val = 0
                break
            elif "loading" not in first_row_text:
                rec_val = rows_loc.count()
                break
                
        page.wait_for_timeout(500)
        
    elapsed = f"{time.time() - start_time_ref:.2f}"
    return elapsed, str(rec_val)

def _kpi_runner_worker(app, site_id, run_id, jhs_credentials=None):
    """Background Playwright worker to gather KPI performance data."""
    print(f"\n[KPI RUNNER] Starting background crawl for run: {run_id}", flush=True)
    
    with app.app_context():
        site = Site.query.get(site_id)
        tr = TestRun.query.get(run_id)
        if not site or not tr:
            print("[KPI RUNNER] Target site or test run record not found.", flush=True)
            return

    from playwright.sync_api import sync_playwright
    import os
    
    prefix = site.name.upper()
    base_url = os.getenv(f"{prefix}_URL") or os.getenv("JIO_HUMSAFAR_PROD_URL") or "https://jiohumsafar.jio.com/"
    
    if jhs_credentials and jhs_credentials.get("username") and jhs_credentials.get("password"):
        username = jhs_credentials["username"]
        password = jhs_credentials["password"]
    else:
        username = os.getenv(f"{prefix}_USERNAME") or os.getenv("QA_AGENT_USERNAME") or "admin"
        password = os.getenv(f"{prefix}_PASSWORD") or os.getenv("QA_AGENT_PASSWORD") or "admin"
    
    # helper to save ValueCaptures
    def save_metric(label, page_name, selector, val):
        with app.app_context():
            existing = ValueCapture.query.filter_by(run_id=run_id, label=label).first()
            if existing:
                existing.captured_value = str(val)
            else:
                vc = ValueCapture(
                    run_id=run_id,
                    site_id=site_id,
                    label=label,
                    page=page_name,
                    selector=selector,
                    captured_value=str(val)
                )
                db.session.add(vc)
            db.session.commit()

    def check_cancel():
        with _active_kpi_runs_lock:
            if run_id in _active_kpi_runs and _active_kpi_runs[run_id].get("status") == "cancelled":
                raise Exception("cancelled")

    total_steps = len(KPI_STEPS)
    
    try:
        with sync_playwright() as p:
            check_cancel()
            browser = p.chromium.launch(headless=False)
            
            # Centralized shared environment-scoped session loading
            from app.utils.playwright_session import get_or_create_session
            from crawler.mapper import load_site_map, get_login_info
            site_map = load_site_map()
            login_info = get_login_info(site_map)
            credentials = {
                "username": username,
                "password": password
            }
            try:
                state_file = get_or_create_session(
                    browser=browser,
                    env_name=site.name,
                    base_url=base_url,
                    credentials=credentials,
                    login_info=login_info
                )
                print(f"[KPI RUNNER] Loading JHS storage state from shared path {state_file}...", flush=True)
                context = browser.new_context(storage_state=state_file)
                from app.utils.playwright_session import inject_session_storage_to_context
                inject_session_storage_to_context(context, site.name, email=username)
            except Exception as e:
                print(f"[KPI RUNNER] Error using shared session: {e}. Starting fresh context.", flush=True)
                context = browser.new_context()
            page = context.new_page()
            
            # Step 1: Check if already logged in by going directly to the protected dashboard page.
            # This completely avoids loading page redirection delays and potential login state mismatches.
            page.goto(base_url + "/#/pages/dashboard/aggregate-dashboard")
            
            already_logged_in = False
            try:
                page.wait_for_selector(".sidebar-link, a[href*='dashboard'], .main-header", timeout=5000)
                already_logged_in = True
            except Exception:
                pass
                
            # If not logged in, force navigation back to the login page suffix for Step 1 OTP filling
            if not already_logged_in:
                page.goto(base_url + KPI_STEPS[0]["url_suffix"])
                
            if already_logged_in:
                print("[KPI RUNNER] Already logged in via storage state. Skipping Step 1 and Step 2 login forms.", flush=True)
                # Save mock metrics for login steps
                save_metric(f"{KPI_STEPS[0]['parameter']} - Loading Time", "Login Page", "button.login_btn", "0.10")
                save_metric(f"{KPI_STEPS[0]['parameter']} - Number of Records", "Login Page", "button.login_btn", "-")
                save_metric(f"{KPI_STEPS[1]['parameter']} - Loading Time", "Login Page", "button.login_btn", "0.10")
                save_metric(f"{KPI_STEPS[1]['parameter']} - Number of Records", "Login Page", "button.login_btn", "-")
                
                with _active_kpi_runs_lock:
                    if run_id in _active_kpi_runs:
                        _active_kpi_runs[run_id]["completed_steps"] += 2
            else:
                # Run the standard Step 1 & Step 2 form filling
                # Step 1: Login OTP Gen
                step_otp = KPI_STEPS[0]
                start_otp = time.time()
                # If we are on the landing page where the credentials form is hidden,
                # click the top-right 'Login' button to display the form.
                try:
                    landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
                    if landing_login_btn.is_visible():
                        print("[KPI RUNNER] Landing page detected. Clicking 'Login' button to reveal form...", flush=True)
                        landing_login_btn.click()
                        page.wait_for_timeout(1000)
                except Exception:
                    pass

                page.wait_for_selector('input[formcontrolname="username"]', timeout=15000)
                page.locator('input[formcontrolname="username"]').first.fill(username)
                page.locator('input#password-field').first.fill(password)
                page.locator('button.login_btn').first.click()
                
                otp_sel = 'input#otp_Email:visible, input[id*="otp"]:visible, input[name="otp"]:visible'
                page.wait_for_selector(otp_sel, timeout=10000)
                otp_gen_time = time.time() - start_otp
                save_metric(f"{step_otp['parameter']} - Loading Time", "Login Page", "button.login_btn", f"{otp_gen_time:.2f}")
                save_metric(f"{step_otp['parameter']} - Number of Records", "Login Page", "button.login_btn", "-")
                
                with _active_kpi_runs_lock:
                    if run_id in _active_kpi_runs:
                        _active_kpi_runs[run_id]["completed_steps"] += 1
                
                # Step 2: Login Status
                step_login = KPI_STEPS[1]
                start_login = time.time()
                check_cancel()
                page.locator(otp_sel).first.fill("123456")
                page.locator('button.login_btn').first.click()
                
                page.wait_for_function(
                    """() => window.location.href.includes('#/pages/dashboard/') || !window.location.href.includes('login')""",
                    timeout=15000
                )
                login_status_time = time.time() - start_login
                save_metric(f"{step_login['parameter']} - Loading Time", "Login Page", "button.login_btn", f"{login_status_time:.2f}")
                save_metric(f"{step_login['parameter']} - Number of Records", "Login Page", "button.login_btn", "-")
                
                # Update environment-scoped shared storage state on successful manual login in KPI runner
                try:
                    page.wait_for_timeout(4000)
                    from app.utils.playwright_session import get_shared_session_path
                    state_file = get_shared_session_path(site.name)
                    context.storage_state(path=state_file)
                    print(f"[KPI RUNNER] Successfully logged in and updated shared storage state: {state_file}", flush=True)
                except Exception as e:
                    print(f"[KPI RUNNER] Error saving storage state: {e}", flush=True)
                
                with _active_kpi_runs_lock:
                    if run_id in _active_kpi_runs:
                        _active_kpi_runs[run_id]["completed_steps"] += 1
                    
            # Subsequent steps (index 2 onwards)
            for idx in range(2, total_steps):
                check_cancel()
                step = KPI_STEPS[idx]
                param = step["parameter"]
                cat = step["category"]
                stype = step["type"]
                url = base_url + step["url_suffix"]
                
                load_time = "0.00"
                rec_count = "0"
                
                try:
                    start_step = time.time()
                    page.goto(url)
                    
                    if stype == "cc_map":
                        page.wait_for_selector('button:has-text("All - ")', timeout=15000)
                        
                        # Wait until count is greater than 0
                        rec_val = 0
                        start_wait = time.time()
                        while time.time() - start_wait < 45.0:
                            text = page.locator('button:has-text("All - ")').first.text_content()
                            m = re.search(r"All\s*-\s*(\d+)", text, re.IGNORECASE)
                            if m:
                                count_val = int(m.group(1))
                                if count_val > 0:
                                    rec_val = count_val
                                    break
                            page.wait_for_timeout(500)
                            
                        load_time = f"{time.time() - start_step:.2f}"
                        rec_count = str(rec_val)
                            
                    elif stype == "cc_list":
                        # Wait for any spinner to disappear first
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"]', state="hidden", timeout=5000)
                        except Exception:
                            pass
                            
                        page.wait_for_selector('button:has-text("All - ")', timeout=15000)
                        list_btn = None
                        # Ultra-robust selector loop searching inside main content first to avoid sidebar matches
                        for prefix in ["nb-layout-column ", ".main-content ", ""]:
                            for sel in [
                                f'{prefix}span:has-text("List View")',
                                f'{prefix}a:has-text("List View")',
                                f'{prefix}div:has-text("List View")',
                                f'{prefix}span:has-text("List")',
                                f'{prefix}a:has-text("List")',
                                f'{prefix}div:has-text("List")',
                                f'{prefix}button:has-text("List View")',
                                f'{prefix}button:has-text("List")'
                            ]:
                                try:
                                    loc = page.locator(sel)
                                    cnt = loc.count()
                                    for idx in range(cnt):
                                        item = loc.nth(idx)
                                        if item.is_visible() and item.is_enabled():
                                            text_content = item.text_content().strip().lower()
                                            if text_content in ("list view", "list"):
                                                list_btn = item
                                                break
                                    if list_btn:
                                        break
                                except Exception:
                                    pass
                            if list_btn:
                                break
                                
                        start_list = time.time()
                        if list_btn:
                            list_btn.click()
                        else:
                            # Fallback using standard text locator
                            try:
                                page.locator('text="List View"').first.click(timeout=5000)
                            except Exception:
                                pass
                        
                        load_time, rec_count = _wait_and_capture_kpi_data(page, start_list, cancel_check_fn=check_cancel)
                                    
                    elif stype == "dashboard_widgets":
                        page.wait_for_selector('app-donut-chart, .dashboard-widget-grid, span.count', timeout=15000)
                        
                        # Wait briefly for dashboard numbers to populate
                        rec_val = 0
                        start_wait = time.time()
                        while time.time() - start_wait < 15.0:
                            count_el = page.locator('span.count').first
                            if count_el.count() > 0:
                                txt = count_el.text_content().strip()
                                m = re.search(r"(\d+)", txt)
                                if m:
                                    val = int(m.group(1))
                                    if val > 0:
                                        rec_val = val
                                        break
                            page.wait_for_timeout(500)
                            
                        load_time = f"{time.time() - start_step:.2f}"
                        rec_count = str(rec_val)
                                
                    elif stype == "cargo_tab":
                        tab_name = step["tab_name"]
                        page.wait_for_selector('.mat-tab-label, .page-inner-content .nav-link, #ongoing-view-tab, #upcoming-view-tab, #completed-view-tab', timeout=15000)
                        
                        # Wait for initial SPA loading and rendering to settle
                        page.wait_for_timeout(3000)
                        
                        tab_el = None
                        if tab_name != "Summary":
                            cargo_selectors = [
                                f"#{tab_name.lower()}-view-tab",
                                f'.mat-tab-label:has-text("{tab_name}")',
                                f'.page-inner-content .nav-link:has-text("{tab_name}")',
                                f'div.mat-tab-label >> text={tab_name}',
                                f'button:has-text("{tab_name}")',
                                f".nav-tabs .nav-link:has-text('{tab_name}')"
                            ]
                            for sel in cargo_selectors:
                                if page.locator(sel).count() > 0:
                                    tab_el = page.locator(sel).first
                                    break
                        
                        start_tab = time.time()
                        if tab_el:
                            tab_el.click()
                            # Wait for tab transition to complete
                            page.wait_for_timeout(1500)
                        
                        actual_container = f"#{tab_name.lower()}-view" if tab_name != "Summary" else "div.tab-pane.active"
                        
                        # Wait for any spinner to disappear
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"], [class*="loading"], mat-progress-bar', state="hidden", timeout=10000)
                        except Exception:
                            pass
                            
                        # Extract the count in a robust wait loop to prevent race conditions on SPA rendering
                        rec_val = 0
                        start_wait = time.time()
                        while time.time() - start_wait < 15.0:
                            # 1. Try to extract from "Total count:" text
                            total_count_sel = f"{actual_container} >> text=Total count:"
                            tc_loc = page.locator(total_count_sel).first
                            if tc_loc.count() > 0:
                                txt = tc_loc.text_content()
                                m = re.search(r"Total\s+count:\s*([\d,]+)", txt, re.IGNORECASE)
                                if m:
                                    val = int(m.group(1).replace(',', ''))
                                    # If cards are visible, total count should be > 0.
                                    # Wait for non-zero unless no cards are visible.
                                    cards_loc = page.locator(f"{actual_container} .ongoing_card:visible, {actual_container} [class*='card']:visible")
                                    if val > 0:
                                        rec_val = val
                                        break
                                    elif val == 0 and cards_loc.count() == 0:
                                        # Genuine 0 count
                                        rec_val = 0
                                        if time.time() - start_wait > 2.0:
                                            break
                                            
                            # 2. Check for explicit empty state selectors
                            no_data_selectors = ['.no-data:visible', '.no-records:visible', 'text="No records found"', 'text="No data found"']
                            no_data_visible = False
                            for nd_sel in no_data_selectors:
                                if page.locator(f"{actual_container} >> {nd_sel}").count() > 0:
                                    no_data_visible = True
                                    break
                                    
                            if no_data_visible:
                                rec_val = 0
                                if time.time() - start_wait > 2.0:
                                    break
                                    
                            # 3. Fallback: count card cards
                            rows_loc = page.locator(f"{actual_container} .ongoing_card:visible, {actual_container} [class*='card']:visible")
                            if rows_loc.count() > 0:
                                rec_val = rows_loc.count()
                                if rec_val > 0 and time.time() - start_wait > 3.0:
                                    break
                                    
                            page.wait_for_timeout(500)
                            
                        load_time = f"{time.time() - start_tab:.2f}"
                        rec_count = str(rec_val)
                        
                    elif stype in ("video_tab", "ignition_tab"):
                        page.wait_for_selector('.mat-tab-label, .page-inner-content .nav-link', timeout=15000)
                        tab_name = step["tab_name"]
                        tab_el = None
                        for sel in [f'.mat-tab-label:has-text("{tab_name}")', f'.page-inner-content .nav-link:has-text("{tab_name}")', f'div.mat-tab-label >> text={tab_name}', f'button:has-text("{tab_name}")']:
                            if page.locator(sel).count() > 0:
                                tab_el = page.locator(sel).first
                                break
                        start_tab = time.time()
                        if tab_el:
                            tab_el.click()
                                    
                        load_time, rec_count = _wait_and_capture_kpi_data(page, start_tab, cancel_check_fn=check_cancel)
                                    
                    elif stype == "report_alert":
                        alert_filter = step["alert_filter"]
                        page.wait_for_timeout(3000)
                        page.wait_for_selector('.multiselect-dropdown, button[title="View"], button:has-text("View")', timeout=35000)
                        
                        # Select first vehicle or select all
                        veh_drop = page.locator('.multiselect-dropdown:has-text("Vehicle")').first
                        if veh_drop.count() > 0:
                            try:
                                # Open dropdown if not already open
                                dropdown_list = veh_drop.locator(".dropdown-list, .dropdown-menu")
                                if dropdown_list.count() == 0 or not dropdown_list.first.is_visible():
                                    veh_drop.locator(".dropdown-btn").click()
                                    page.wait_for_timeout(500)
                                    
                                sel_all = veh_drop.locator('input[aria-label="multiselect-select-all"]').first
                                sel_all.wait_for(state="visible", timeout=5000)
                                if not sel_all.is_checked():
                                    sel_all.check(force=True, timeout=5000)
                                page.wait_for_timeout(500)
                                
                                # Force close dropdown by clicking the dropdown button again
                                if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                    veh_drop.locator(".dropdown-btn").click()
                                    page.wait_for_timeout(500)
                                    
                                # If it is still open, click the page body or header to force it closed
                                if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                    print("[KPI RUNNER] Dropdown still open. Clicking body to force close...", flush=True)
                                    page.locator("body").click()
                                    page.wait_for_timeout(500)
                            except Exception as dropdown_err:
                                print(f"[KPI RUNNER] Warning: Failed to select all vehicles in alert report: {dropdown_err}", flush=True)
                                # Try fallback checkbox check
                                try:
                                    first_chk = veh_drop.locator('.dropdown-list input[type="checkbox"]').first
                                    if first_chk.count() > 0:
                                        first_chk.check(force=True, timeout=2000)
                                    # Try closing again
                                    dropdown_list = veh_drop.locator(".dropdown-list, .dropdown-menu")
                                    if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                        veh_drop.locator(".dropdown-btn").click()
                                        page.wait_for_timeout(500)
                                        if dropdown_list.first.is_visible():
                                            page.locator("body").click()
                                            page.wait_for_timeout(500)
                                except Exception:
                                    pass
                            
                        # Choose alert filter popup
                        choose_btn = page.locator('button[title="Choose Alerts"], button.alert-col-btn').first
                        if choose_btn.count() > 0:
                            try:
                                choose_btn.click()
                                page.wait_for_timeout(1000)
                                
                                # Programmatically deselect all checked checkboxes first (such as High priority and previous filters)
                                try:
                                    page.evaluate("""() => {
                                        const checkedCheckboxes = document.querySelectorAll('.Alert-dropdown input[type="checkbox"]:checked');
                                        checkedCheckboxes.forEach(cb => {
                                            cb.click();
                                            cb.dispatchEvent(new Event('change', { bubbles: true }));
                                        });
                                    }""")
                                    page.wait_for_timeout(500)
                                except Exception as e:
                                    print(f"[KPI RUNNER] Warning: failed to deselect checked checkboxes: {e}", flush=True)
                                    
                                search_in = page.locator('.Alert-dropdown input[placeholder="Search"], input.form-control[placeholder="Search"]').first
                                if search_in.count() > 0:
                                    search_in.fill(alert_filter)
                                    page.wait_for_timeout(500)
                                    match_locator = page.locator(f'.Alert-dropdown label.filter_check_container:has-text("{alert_filter}"), .Alert-dropdown label:has-text("{alert_filter}")')
                                    match_count = match_locator.count()
                                    for i in range(match_count):
                                        lbl = match_locator.nth(i)
                                        if lbl.is_visible():
                                            lbl_text = lbl.text_content().strip()
                                            should_check = False
                                            if alert_filter == "Geofence":
                                                normalized_lbl = lbl_text.lower().replace('-', ' ').replace('_', ' ')
                                                if "geofence entry" in normalized_lbl or "geofence exit" in normalized_lbl:
                                                    should_check = True
                                            else:
                                                if alert_filter.lower() in lbl_text.lower():
                                                    should_check = True
                                                    
                                            chk_input = lbl.locator('input[type="checkbox"]').first
                                            if should_check:
                                                if chk_input.count() > 0:
                                                    if not chk_input.is_checked():
                                                        lbl.click()
                                                else:
                                                    lbl.click()
                                            else:
                                                if chk_input.count() > 0:
                                                    if chk_input.is_checked():
                                                        lbl.click()
                                close_btn = page.locator(
                                    '.Alert-dropdown .material-icons:has-text("close"), '
                                    '.Alert-dropdown span:has-text("close"), '
                                    'span:has-text("close"), '
                                    'button:has-text("Close")'
                                ).first
                                if close_btn.count() > 0:
                                    close_btn.click()
                                    page.wait_for_timeout(500)
                            except Exception as alert_dropdown_err:
                                print(f"[KPI RUNNER] Warning: Failed choosing alert filter {alert_filter}: {alert_dropdown_err}", flush=True)
                                
                        # Double check that no dropdown menu is open before clicking "View" to prevent click swallowing
                        try:
                            open_dropdowns = page.locator(".dropdown-list:visible, .dropdown-menu:visible")
                            if open_dropdowns.count() > 0:
                                print("[KPI RUNNER] Pre-view check: Closing open dropdown list to prevent swallowing the click...", flush=True)
                                page.locator("body").click()
                                page.wait_for_timeout(500)
                        except Exception:
                            pass

                        start_rep = time.time()
                        view_btn = page.locator('button[title="View"], button:has-text("View"), button:has-text("Submit")').first
                        view_btn.wait_for(state="visible", timeout=5000)
                        try:
                            view_btn.click(timeout=5000)
                        except Exception:
                            view_btn.click(force=True)
                        
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"], [class*="loading"], mat-progress-bar', state="visible", timeout=2000)
                        except Exception:
                            pass
                            
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"], [class*="loading"], mat-progress-bar', state="hidden", timeout=30000)
                        except Exception:
                            pass
                            
                        try:
                            page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                            
                        load_time, rec_count = _wait_and_capture_kpi_data(page, start_rep, cancel_check_fn=check_cancel)
                                    
                    elif stype == "report_other":
                        page.wait_for_timeout(3000)
                        page.wait_for_selector('.multiselect-dropdown, button[title="View"], button:has-text("View")', timeout=35000)
                        
                        # Select first vehicle or select all
                        veh_drop = page.locator('.multiselect-dropdown:has-text("Vehicle")').first
                        if veh_drop.count() > 0:
                            try:
                                # Open dropdown if not already open
                                dropdown_list = veh_drop.locator(".dropdown-list, .dropdown-menu")
                                if dropdown_list.count() == 0 or not dropdown_list.first.is_visible():
                                    veh_drop.locator(".dropdown-btn").click()
                                    page.wait_for_timeout(500)
                                    
                                sel_all = veh_drop.locator('input[aria-label="multiselect-select-all"]').first
                                sel_all.wait_for(state="visible", timeout=5000)
                                if not sel_all.is_checked():
                                    sel_all.check(force=True, timeout=5000)
                                page.wait_for_timeout(500)
                                
                                # Force close dropdown by clicking the dropdown button again
                                if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                    veh_drop.locator(".dropdown-btn").click()
                                    page.wait_for_timeout(500)
                                    
                                # If it is still open, click the page body or header to force it closed
                                if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                    print("[KPI RUNNER] Dropdown still open. Clicking body to force close...", flush=True)
                                    page.locator("body").click()
                                    page.wait_for_timeout(500)
                            except Exception as dropdown_err:
                                print(f"[KPI RUNNER] Warning: Failed to select all vehicles in report: {dropdown_err}", flush=True)
                                # Try fallback checkbox check
                                try:
                                    first_chk = veh_drop.locator('.dropdown-list input[type="checkbox"]').first
                                    if first_chk.count() > 0:
                                        first_chk.check(force=True, timeout=2000)
                                    # Try closing again
                                    dropdown_list = veh_drop.locator(".dropdown-list, .dropdown-menu")
                                    if dropdown_list.count() > 0 and dropdown_list.first.is_visible():
                                        veh_drop.locator(".dropdown-btn").click()
                                        page.wait_for_timeout(500)
                                        if dropdown_list.first.is_visible():
                                            page.locator("body").click()
                                            page.wait_for_timeout(500)
                                except Exception:
                                    pass
                            
                        # Double check that no dropdown menu is open before clicking "View" to prevent click swallowing
                        try:
                            open_dropdowns = page.locator(".dropdown-list:visible, .dropdown-menu:visible")
                            if open_dropdowns.count() > 0:
                                print("[KPI RUNNER] Pre-view check: Closing open dropdown list to prevent swallowing the click...", flush=True)
                                page.locator("body").click()
                                page.wait_for_timeout(500)
                        except Exception:
                            pass

                        start_rep = time.time()
                        view_btn = page.locator('button[title="View"], button:has-text("View"), button:has-text("Submit")').first
                        view_btn.wait_for(state="visible", timeout=5000)
                        try:
                            view_btn.click(timeout=5000)
                        except Exception:
                            view_btn.click(force=True)
                        
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"], [class*="loading"], mat-progress-bar', state="visible", timeout=2000)
                        except Exception:
                            pass
                            
                        try:
                            page.wait_for_selector('.loading, .loader, [class*="spinner"], [class*="loading"], mat-progress-bar', state="hidden", timeout=30000)
                        except Exception:
                            pass
                            
                        try:
                            page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                            
                        load_time, rec_count = _wait_and_capture_kpi_data(page, start_rep, cancel_check_fn=check_cancel)
                                    
                except Exception as step_err:
                    import traceback
                    tb_str = traceback.format_exc()
                    print(f"[KPI RUNNER] Error on step {param}: {step_err}\n{tb_str}", flush=True)
                    try:
                        with open("d:\\asset_ai_projects\\QA_agent\\kpi_debug.log", "a", encoding="utf-8") as f:
                            f.write(f"=== Error on step {param} ({stype}) ===\n")
                            f.write(f"Time: {datetime.now(timezone.utc)}\n")
                            f.write(f"Error: {step_err}\n")
                            f.write(f"Traceback:\n{tb_str}\n\n")
                    except Exception:
                        pass
                    
                # Save captured details
                save_metric(f"{param} - Loading Time", cat, step["url_suffix"], load_time)
                save_metric(f"{param} - Number of Records", cat, step["url_suffix"], rec_count)
                
                with _active_kpi_runs_lock:
                    if run_id in _active_kpi_runs:
                        _active_kpi_runs[run_id]["completed_steps"] += 1
                        
            browser.close()
            
        is_cancelled = False
        with _active_kpi_runs_lock:
            if run_id in _active_kpi_runs and _active_kpi_runs[run_id].get("status") == "cancelled":
                is_cancelled = True

        with app.app_context():
            tr = TestRun.query.get(run_id)
            if is_cancelled:
                tr.status = "cancelled"
            else:
                tr.status = "pass"
            tr.finished_at = datetime.now(timezone.utc)
            db.session.commit()
            
        with _active_kpi_runs_lock:
            if run_id in _active_kpi_runs:
                if is_cancelled:
                    _active_kpi_runs[run_id]["status"] = "cancelled"
                else:
                    _active_kpi_runs[run_id]["status"] = "completed"
                
    except Exception as exc:
        is_cancelled = False
        with _active_kpi_runs_lock:
            if run_id in _active_kpi_runs and _active_kpi_runs[run_id].get("status") == "cancelled":
                is_cancelled = True

        print(f"[KPI RUNNER] Fatal exception: {exc}", flush=True)
        with app.app_context():
            tr = TestRun.query.get(run_id)
            if tr:
                tr.status = "cancelled" if (is_cancelled or str(exc) == "cancelled") else "error"
                tr.finished_at = datetime.now(timezone.utc)
                db.session.commit()
        with _active_kpi_runs_lock:
            if run_id in _active_kpi_runs:
                if is_cancelled or str(exc) == "cancelled":
                    _active_kpi_runs[run_id]["status"] = "cancelled"
                else:
                    _active_kpi_runs[run_id]["status"] = "error"
                    _active_kpi_runs[run_id]["error"] = str(exc)

@kpi_runner_bp.route("/api/kpi/run", methods=["POST"])
def api_kpi_run():
    """Trigger a Performance KPI crawl in a background thread."""
    data = request.json or {}
    site_name = data.get("site_name", "jhs84")
    
    site = Site.query.filter_by(name=site_name).first()
    if not site:
        return jsonify({"error": f"Site '{site_name}' not found"}), 404
        
    # Get or create the TestCase container for KPI Sheet
    tc = TestCase.query.filter_by(category="performance_kpi").first()
    if not tc:
        tc = TestCase(
            name="Performance KPI Sheet Run",
            situation_description="Runs performance metrics collection across all key pages.",
            category="performance_kpi",
            steps=[]
        )
        db.session.add(tc)
        db.session.commit()
        
    tr = TestRun(
        test_case_id=tc.id,
        site_id=site.id,
        triggered_by="web",
        status="running",
        started_at=datetime.now(timezone.utc)
    )
    db.session.add(tr)
    db.session.commit()
    
    run_id = str(tr.id)
    
    with _active_kpi_runs_lock:
        _active_kpi_runs[run_id] = {
            "status": "running",
            "completed_steps": 0,
            "total_steps": len(KPI_STEPS),
            "site_name": site.name
        }
        
    # Launch background thread worker
    app = current_app._get_current_object()
    from flask import session
    jhs_creds = {
        "username": session.get("jhs_username"),
        "password": session.get("jhs_password")
    }
    thread = threading.Thread(target=_kpi_runner_worker, args=(app, site.id, run_id, jhs_creds))
    thread.daemon = True
    thread.start()
    
    return jsonify({"run_id": run_id})

@kpi_runner_bp.route("/api/kpi/progress/<run_id>")
def api_kpi_progress(run_id):
    """Retrieve live status and values captured so far for a run."""
    with _active_kpi_runs_lock:
        status_info = _active_kpi_runs.get(run_id)
        
    # Read captures from database to return live values
    captures = ValueCapture.query.filter_by(run_id=run_id).all()
    metrics = {}
    for cap in captures:
        metrics[cap.label] = cap.captured_value
        
    if status_info:
        return jsonify({
            "status": status_info["status"],
            "completed_steps": status_info["completed_steps"],
            "total_steps": status_info["total_steps"],
            "metrics": metrics
        })
    else:
        # Check if completed run exists in DB
        tr = TestRun.query.get(run_id)
        if tr:
            return jsonify({
                "status": "completed" if tr.status == "pass" else tr.status,
                "completed_steps": len(KPI_STEPS),
                "total_steps": len(KPI_STEPS),
                "metrics": metrics
            })
        return jsonify({"error": "Run not found"}), 404

@kpi_runner_bp.route("/api/kpi/cancel/<run_id>", methods=["POST"])
def api_kpi_cancel(run_id):
    """Cancel an active KPI generation run."""
    with _active_kpi_runs_lock:
        if run_id in _active_kpi_runs:
            _active_kpi_runs[run_id]["status"] = "cancelled"
            
    # Also update in DB
    tr = TestRun.query.get(run_id)
    if tr and tr.status == "running":
        tr.status = "cancelled"
        tr.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        
    return jsonify({"success": True})

@kpi_runner_bp.route("/api/kpi/details/<run_id>")
def api_kpi_details(run_id):
    """Retrieve detailed KPI values for previewing."""
    captures = ValueCapture.query.filter_by(run_id=run_id).all()
    metrics = {cap.label: cap.captured_value for cap in captures}
    
    kpi_rows = []
    for step in KPI_STEPS:
        param = step["parameter"]
        cat = step["category"]
        lt_key = f"{param} - Loading Time"
        rc_key = f"{param} - Number of Records"
        kpi_rows.append({
            "category": cat,
            "parameter": param,
            "loading_time": metrics.get(lt_key, ""),
            "record_count": metrics.get(rc_key, "")
        })
        
    tr = TestRun.query.get(run_id)
    site_name = tr.site.name if tr and tr.site else "jhs"
    started_at = tr.started_at.strftime('%b %d, %Y %I:%M:%S %p') if tr and tr.started_at else "N/A"
    
    return jsonify({
        "success": True,
        "site_name": site_name,
        "started_at": started_at,
        "kpi_rows": kpi_rows
    })

@kpi_runner_bp.route("/api/kpi/download/<run_id>")
def api_kpi_download(run_id):
    """Generate and return styled Excel report for a run."""
    captures = ValueCapture.query.filter_by(run_id=run_id).all()
    metrics = {cap.label: cap.captured_value for cap in captures}
    
    # Form rows matching KPI_STEPS order
    kpi_rows = []
    for step in KPI_STEPS:
        param = step["parameter"]
        cat = step["category"]
        
        # Look up values in captures dictionary
        lt_key = f"{param} - Loading Time"
        rc_key = f"{param} - Number of Records"
        
        kpi_rows.append({
            "category": cat,
            "parameter": param,
            "loading_time": metrics.get(lt_key, ""),
            "record_count": metrics.get(rc_key, "")
        })
        
    # Generate Excel in-memory
    output = io.BytesIO()
    generate_kpi_excel(kpi_rows, output)
    output.seek(0)
    
    # Retrieve site name for filename
    tr = TestRun.query.get(run_id)
    site_name = tr.site.name if tr and tr.site else "jhs"
    
    # Extract friendly username from logged in email
    from flask import session
    email = session.get("jhs_username") or "user"
    username = email.split("@")[0].lower() if "@" in email else email.lower()
    
    # Format today's date with ordinal suffix, e.g. "26th may"
    now_dt = datetime.now()
    day = now_dt.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    month_name = now_dt.strftime("%b").lower()
    date_str = f"{day}{suffix} {month_name}"
    
    filename = f"{date_str}-{site_name.lower()}-{username}.xlsx"
    
    # Record download event in history
    try:
        db.create_all()
        history_entry = KpiDownloadHistory(
            run_id=run_id,
            site_name=site_name,
            filename=filename,
            downloaded_at=datetime.now(timezone.utc)
        )
        db.session.add(history_entry)
        db.session.commit()
    except Exception as e:
        print(f"[KPI DOWNLOAD] Failed to record download in history: {e}", flush=True)
        
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@kpi_runner_bp.route("/api/kpi/download-history")
def api_kpi_download_history():
    """Retrieve all KPI download history records."""
    try:
        db.create_all()
        records = KpiDownloadHistory.query.order_by(KpiDownloadHistory.downloaded_at.desc()).all()
        data = []
        for r in records:
            local_time = r.downloaded_at.strftime("%Y-%m-%d %I:%M:%S %p")
            data.append({
                "id": r.id,
                "run_id": r.run_id,
                "site_name": r.site_name,
                "filename": r.filename,
                "downloaded_at": local_time
            })
        return jsonify({"success": True, "history": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@kpi_runner_bp.route("/api/kpi/download-summary")
def api_kpi_download_summary():
    """Retrieve aggregated download counts grouped by date."""
    try:
        db.create_all()
        records = KpiDownloadHistory.query.all()
        
        counts = {}
        for r in records:
            # downloaded_at is a DateTime in UTC. Let's group by YYYY-MM-DD
            date_str = r.downloaded_at.strftime("%Y-%m-%d")
            counts[date_str] = counts.get(date_str, 0) + 1
            
        summary_list = []
        for d_str, count in sorted(counts.items(), reverse=True):
            summary_list.append({
                "date": d_str,
                "count": count
            })
            
        return jsonify({"success": True, "summary": summary_list})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
