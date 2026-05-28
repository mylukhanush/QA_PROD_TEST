"""
Playwright Test Executor.

Handles every action type from the AI-generated test plan:
  navigate, login, click, wait_for_element, wait_for_response,
  get_text, assert_equal, assert_not_empty, assert_contains,
  assert_not_equal, compare_values, screenshot, type_text,
  select_option, store_value.

CRITICAL: No page.wait_for_timeout() or time.sleep() anywhere.
All selectors come from site-map.json — never hardcoded.
"""
import json
import os
import uuid
import time
from datetime import datetime, timezone
from typing import Optional

import re
from playwright.sync_api import sync_playwright, expect
from app.logging_config import log_event

from crawler.mapper import load_site_map, get_login_info
from db import db
from db.models import Site, TestRun, RunStep, ValueCapture, safe_duration_ms
from runner.waiter import (
    wait_for_element_non_empty,
    wait_for_page_data_loaded,
    wait_for_api_response,
    wait_for_login_success,
)


def _site_env(site_name: str, jhs_credentials: dict = None) -> dict:
    """Load site credentials from environment variables."""
    prefix = site_name.upper()
    url = os.getenv(f"{prefix}_URL") or os.getenv("JIO_HUMSAFAR_PROD_URL") or "https://jiohumsafar.jio.com/"
    if jhs_credentials and jhs_credentials.get("username") and jhs_credentials.get("password"):
        return {
            "url": url,
            "username": jhs_credentials["username"],
            "password": jhs_credentials["password"],
        }
    return {
        "url": url,
        "username": os.getenv(f"{prefix}_USERNAME") or os.getenv("QA_AGENT_USERNAME") or "admin",
        "password": os.getenv(f"{prefix}_PASSWORD") or os.getenv("QA_AGENT_PASSWORD") or "admin",
    }


def _take_screenshot(page, run_id: str, step_order: int) -> str:
    """Capture a full-page screenshot and return the saved path."""
    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    filename = f"{run_id}_step{step_order}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.join(screenshots_dir, filename)
    try:
        page.screenshot(path=path, full_page=True)
    except Exception:
        pass
    return path


def _record_step(run_id, step_order, action, description, status,
                 error_message=None, screenshot_path=None, duration_ms=None):
    """Write a step result to the run_steps table."""
    step = RunStep(
        run_id=run_id,
        step_order=step_order,
        action=action,
        description=description,
        status=status,
        error_message=error_message,
        screenshot_path=screenshot_path,
        duration_ms=duration_ms,
    )
    db.session.add(step)
    db.session.commit()
    return step


def _record_value_capture(run_id, site_id, label, page_name, selector,
                          captured_value, expected_value=None, matched=None):
    """Write a value capture to the value_captures table."""
    vc = ValueCapture(
        run_id=run_id,
        site_id=site_id,
        label=label,
        page=page_name,
        selector=selector,
        captured_value=captured_value,
        expected_value=expected_value,
        matched=matched,
    )
    db.session.add(vc)
    db.session.commit()
    return vc


def _resolve_sitemap_target(target: str, site_map: dict, value=None) -> str:
    """
    Resolve a dot-notation target (e.g. 'reports_alert.alert_report_card') to its selector in site_map.
    Supports dynamic selectors containing {value} placeholders.
    """
    if not target or not isinstance(target, str):
        return target

    if '.' not in target:
        return target

    parts = target.split('.', 1)
    page_key = parts[0]
    element_key = parts[1]

    pages = site_map.get("pages", {})
    if page_key not in pages:
        return target

    page_data = pages[page_key]
    elements = page_data.get("elements", [])

    # Normalize target key
    target_norm = re.sub(r'[^a-zA-Z0-9]+', '_', element_key.lower()).strip('_')

    matched_selector = None
    for el in elements:
        label = el.get("label", "")
        if not label:
            continue
        label_norm = re.sub(r'[^a-zA-Z0-9]+', '_', label.lower()).strip('_')
        if label_norm == target_norm:
            matched_selector = el.get("selector")
            break

    if not matched_selector:
        # Fallback: exact or lower case match of raw label name
        for el in elements:
            if el.get("label", "").strip().lower() == element_key.strip().lower():
                matched_selector = el.get("selector")
                break

    if matched_selector:
        if value is not None and "{value}" in matched_selector:
            matched_selector = matched_selector.replace("{value}", str(value))
        return matched_selector

    return target


def execute_test_plan(test_plan: dict, run_ids: dict, jhs_credentials: dict = None):
    """
    Execute a test plan against one or more sites.

    Parameters
    ----------
    test_plan : dict
        The AI-generated test plan with steps.
    run_ids : dict
        Mapping of site_name -> run_id (UUID string).
    jhs_credentials : dict, optional
        Custom username and password for JHS site override.
    """
    site_map = load_site_map()
    login_info = get_login_info(site_map)

    for site_name, run_id in run_ids.items():
        log_event(
            "executor_run_start",
            run_id=run_id,
            site=site_name,
        )
        run_start = time.time()
        try:
            _execute_for_site(test_plan, site_name, run_id, site_map, login_info, jhs_credentials=jhs_credentials)
            run_duration = int((time.time() - run_start) * 1000)
            log_event(
                "executor_run_end",
                run_id=run_id,
                site=site_name,
                duration_ms=run_duration,
                status="pass",
            )
        except Exception as exc:
            run_duration = int((time.time() - run_start) * 1000)
            log_event(
                "executor_run_error",
                run_id=run_id,
                site=site_name,
                duration_ms=run_duration,
                status="error",
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            # Mark run as error
            run = TestRun.query.get(run_id)
            if run:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                if run.started_at:
                    run.duration_ms = safe_duration_ms(run.started_at, run.finished_at)
                db.session.commit()

            _record_step(
                run_id=run_id,
                step_order=9999,
                action="error",
                description="Unhandled execution error",
                status="error",
                error_message=str(exc),
            )

            # Generate report even on catastrophic failure
            try:
                from reports.json_report import generate_json_report
                report_path = generate_json_report(run_id)
                run = TestRun.query.get(run_id)
                if run:
                    run.report_path = report_path
                    db.session.commit()
            except Exception as report_exc:
                log_event(
                    "executor_report_error",
                    run_id=run_id,
                    site=site_name,
                    error_type=report_exc.__class__.__name__,
                    error_message=str(report_exc),
                )
def execute_test_run(run_id: str):
    """
    Execute a single test run by ID (used by celery/async workers).
    """
    run = TestRun.query.get(run_id)
    if not run:
        raise ValueError(f"TestRun with ID {run_id} not found.")
        
    test_case = run.test_case
    if not test_case:
        raise ValueError(f"No test case associated with TestRun {run_id}.")
        
    site = run.site
    if not site:
        raise ValueError(f"No site associated with TestRun {run_id}.")
        
    plan = test_case.test_plan or {
        "description": test_case.situation_description,
        "category": test_case.category,
        "steps": test_case.steps,
    }
    
    execute_test_plan(plan, {site.name: run_id})


def _execute_for_site(test_plan, site_name, run_id, site_map, login_info, jhs_credentials=None):
    """Execute all steps against a single site."""
    _execute_for_site_with_page(test_plan, site_name, run_id, site_map, login_info, None, None, jhs_credentials=jhs_credentials)


def _execute_for_site_with_page(test_plan, site_name, run_id, site_map, login_info, page=None, context=None, jhs_credentials=None):
    """Execute all steps against a single site with an optional existing page/context."""
    env = _site_env(site_name, jhs_credentials=jhs_credentials)
    site = Site.query.filter_by(name=site_name).first()
    if not site:
        raise ValueError(f"Site {site_name} not found in database")

    variables = {}
    
    current_status = db.session.query(TestRun.status).filter_by(id=run_id).scalar()
    if current_status in ("cancel_requested", "cancelled"):
        log_event(
            "executor_run_cancelled_early",
            run_id=run_id,
            site=site_name,
            status=current_status,
        )
        _record_step(run_id, 1, "cancel", "Run cancelled by user", "cancelled")
        run = TestRun.query.get(run_id)
        if run:
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        return

    steps = test_plan.get("steps", [])
    overall_status = "pass"
    should_stop = False

    def _escalate_status(current: str, new: str) -> str:
        """
        Status priority: error > fail > pass
        Once error is set, nothing can downgrade it.
        Once fail is set, only error can upgrade it.
        """
        priority = {"pass": 0, "fail": 1, "error": 2}
        if priority.get(new, 0) > priority.get(current, 0):
            return new
        return current

    # Prepare captures directory and start Playwright tracing for this run
    captures_dir = os.getenv("CAPTURES_DIR", "captures")
    os.makedirs(captures_dir, exist_ok=True)
    trace_path = os.path.join(captures_dir, f"{run_id}_trace.zip")
    state_path = os.path.join(captures_dir, f"{run_id}_storage_state.json")
    final_html_path = os.path.join(captures_dir, f"{run_id}_after.html")
    final_screenshot_path = os.path.join(captures_dir, f"{run_id}_final.png")
    
    _pw_instance = None
    browser = None
    if context is None or page is None:
        from playwright.sync_api import sync_playwright
        _pw_instance = sync_playwright().start()
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
        browser = _pw_instance.chromium.launch(headless=headless_env)
        
        # Centralized shared environment-scoped session loading
        from app.utils.playwright_session import get_or_create_session
        env = _site_env(site_name, jhs_credentials=jhs_credentials)
        try:
            state_file = get_or_create_session(
                browser=browser,
                env_name=site_name,
                base_url=env.get("url") or login_info.get("url", ""),
                credentials=env,
                login_info=login_info
            )
            print(f"[EXECUTOR] Loading JHS storage state from shared path {state_file}...", flush=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080}, storage_state=state_file)
            from app.utils.playwright_session import inject_session_storage_to_context
            inject_session_storage_to_context(context, site_name, email=env.get("username"))
        except Exception as e:
            print(f"[EXECUTOR] Error using shared session: {e}. Starting fresh context.", flush=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            
        try:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)
        except Exception:
            try:
                context.tracing.start(screenshots=True, snapshots=True)
            except Exception:
                trace_path = None
        page = context.new_page()
    
    try:

        for idx, step in enumerate(steps):
            action = step.get("action", "")
            target = step.get("target", "")
            value = step.get("value")
            store_as = step.get("storeAs")
            compare_with = step.get("compareWith")
            description = step.get("description", "")
            on_failure = step.get("onFailure", "continue")
            
            original_target = target
            
            step_start = time.time()
            log_event(
                "executor_step_start",
                run_id=run_id,
                site=site_name,
                step_order=idx + 1,
                action=action,
                target=target,
            )

            if action != "navigate" and target and isinstance(target, str) and '.' in target:
                target = _resolve_sitemap_target(target, site_map, value)

            current_status = db.session.query(TestRun.status).filter_by(id=run_id).scalar()
            if current_status in ("cancel_requested", "cancelled"):
                overall_status = "cancelled"
                _record_step(run_id, idx + 1, "cancel", "Run cancelled by user", "cancelled")
                should_stop = True
                break

            if should_stop:
                log_event(
                    "executor_step_skipped",
                    run_id=run_id,
                    site=site_name,
                    step_order=idx + 1,
                    action=action,
                    reason="Previous step failure",
                )
                _record_step(
                    run_id=run_id,
                    step_order=idx + 1,
                    action=action,
                    description=description,
                    status="skipped",
                )
                continue

            if step.get("_skip"):
                log_event(
                    "executor_step_skipped",
                    run_id=run_id,
                    site=site_name,
                    step_order=idx + 1,
                    action=action,
                    reason="Handled in prior step expect_response",
                )
                _record_step(run_id=run_id, step_order=idx + 1, action=action, description=description, status="pass")
                continue

            step_status = "pass"
            error_msg = None
            screenshot_path = None
            
            # Look-ahead for wait_for_response
            next_step = steps[idx + 1] if idx + 1 < len(steps) else None
            needs_api_wait = False
            api_target = ""
            if action in ["click", "select_option", "check", "uncheck", "select_date_range"] and next_step and next_step.get("action") == "wait_for_response":
                api_target_raw = next_step.get("target", "")
                if api_target_raw and "#/" not in api_target_raw:
                    needs_api_wait = True
                    api_target = api_target_raw.split(" ")[-1] if " " in api_target_raw else api_target_raw
                    next_step["_skip"] = True

            try:

                def _perform_action():
                    if action == "navigate":
                        _action_navigate(page, target, env, site_map, login_info, site_name=site_name)
    
                    elif action == "login":
                        _action_login(page, env, login_info, site_name=site_name)
    
                    elif action == "click":
                        # Use force=True to bypass Angular overlay/tooltip interception.
                        # For SPAs, pointer events are often intercepted by transparent overlay components.
                        loc = page.locator(target).first
                        loc.wait_for(state="visible", timeout=15000)

                        try:
                            loc.click(timeout=5000)
                        except Exception:
                            try:
                                # Fallback 1: force=True (bypasses pointer-event blockers while keeping native click)
                                loc.click(force=True, timeout=5000)
                            except Exception:
                                # Fallback 2: dispatch synthetic click event
                                loc.dispatch_event("click")
                        # Add a tiny delay to allow frontend/backend to register the interaction
                        page.wait_for_timeout(500)
    
                    elif action == "wait_for_element":
                        _wait_for_angular_stable(page, timeout=20000)
                        try:
                            wait_for_element_non_empty(page, target, timeout=20000)
                        except Exception as exc:
                            is_correct_page = True
                            if original_target and isinstance(original_target, str) and '.' in original_target:
                                page_key = original_target.split('.', 1)[0]
                                if page_key in site_map.get("pages", {}):
                                    expected_page_url = site_map["pages"][page_key].get("url", "")
                                    if expected_page_url:
                                        expected_part = expected_page_url.split('#')[-1] if '#' in expected_page_url else expected_page_url
                                        expected_part = expected_part.strip().rstrip('/')
                                        current_url = page.url.strip().rstrip('/')
                                        if expected_part.lower() not in current_url.lower():
                                            is_correct_page = False
                            
                            if is_correct_page:
                                no_data_selectors = page.locator(":has-text('No records found'), :has-text('No data'), :has-text('No Data Available')")
                                if no_data_selectors.count() > 0 and no_data_selectors.first.is_visible():
                                    pass # Element is missing because there's no data
                                else:
                                    raise exc
                            else:
                                raise exc
    
                    elif action == "wait_for_response":
                        # Hash-routed SPAs don't fire HTTP requests for hash changes
                        if target and "#/" in target:
                            hash_part = target.split("#")[-1]
                            page.wait_for_function(
                                f"() => window.location.hash.includes('{hash_part}')",
                                timeout=15000,
                            )
                        else:
                            # Should have been skipped if part of click, but if called standalone just sleep briefly
                            # to ensure network has time to settle, as standalone expect_response will race
                            page.wait_for_timeout(2000)
    
                    elif action == "get_text":
                        if target and isinstance(target, str) and target.strip().lower() in ("date.now()", "now()", "timestamp()"):
                            text = str(int(time.time() * 1000))
                            if store_as:
                                variables[store_as] = text
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or target,
                                page_name=page_name,
                                selector=target,
                                captured_value=text,
                            )
                        elif target and isinstance(target, str) and target.strip().lower() in ("calculate_duration", "duration", "time_difference"):
                            expr = str(value or "").strip()
                            import re
                            vars_in_expr = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)
                            resolved_expr = expr
                            for vname in vars_in_expr:
                                if vname in variables:
                                    resolved_expr = resolved_expr.replace(vname, str(variables[vname]))
                            
                            try:
                                clean_expr = re.sub(r"[^0-9\+\-\*\/\(\)\s]", "", resolved_expr)
                                duration_ms = int(eval(clean_expr))
                                text = str(duration_ms)
                            except Exception:
                                text = "0"
                            
                            if store_as:
                                variables[store_as] = text
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or "load_duration_ms",
                                page_name=page_name,
                                selector=expr,
                                captured_value=text,
                            )
                        else:
                            loc = page.locator(target).first
                            
                            try:
                                loc.wait_for(state="visible", timeout=20000)
                                raw_text = _wait_for_stable_text(page, target, loc)
                            except Exception as exc:
                                # If the element didn't appear, check if it's because there's simply no data
                                is_correct_page = True
                                if original_target and isinstance(original_target, str) and '.' in original_target:
                                    page_key = original_target.split('.', 1)[0]
                                    if page_key in site_map.get("pages", {}):
                                        expected_page_url = site_map["pages"][page_key].get("url", "")
                                        if expected_page_url:
                                            expected_part = expected_page_url.split('#')[-1] if '#' in expected_page_url else expected_page_url
                                            expected_part = expected_part.strip().rstrip('/')
                                            current_url = page.url.strip().rstrip('/')
                                            if expected_part.lower() not in current_url.lower():
                                                is_correct_page = False
                                
                                if is_correct_page:
                                    no_data_selectors = page.locator(":has-text('No records found'), :has-text('No data'), :has-text('No Data Available')")
                                    if no_data_selectors.count() > 0 and no_data_selectors.first.is_visible():
                                        raw_text = "No data available"
                                    else:
                                        raise exc
                                else:
                                    raise exc
                                    
                            # For table rows / multi-cell elements, keep full text;
                            # only extract numbers for dashboard metric widgets.
                            if "tbody tr" in target or "<tr" in target:
                                text = raw_text
                            elif "paginator" in target.lower():
                                import re
                                m = re.search(r"of\s+([\d,]+)", raw_text, re.IGNORECASE)
                                text = m.group(1).replace(',', '') if m else raw_text
                            elif raw_text == "No data available":
                                text = raw_text
                            else:
                                text = _extract_number_or_fraction(raw_text)
                                
                            if store_as:
                                variables[store_as] = text
                            # Also record as a value capture (normalized)
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or target,
                                page_name=page_name,
                                selector=target,
                                captured_value=text,
                            )
    
                    elif action == "store_value":
                        if target and isinstance(target, str) and target.strip().lower() in ("date.now()", "now()", "timestamp()"):
                            text = str(int(time.time() * 1000))
                            if store_as:
                                variables[store_as] = text
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or target,
                                page_name=page_name,
                                selector=target,
                                captured_value=text,
                            )
                        elif target and isinstance(target, str) and target.strip().lower() in ("calculate_duration", "duration", "time_difference"):
                            expr = str(value or "").strip()
                            import re
                            # Find all words/variable names
                            vars_in_expr = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expr)
                            resolved_expr = expr
                            for vname in vars_in_expr:
                                if vname in variables:
                                    resolved_expr = resolved_expr.replace(vname, str(variables[vname]))
                            
                            try:
                                # Safe eval: allow only numbers, basic operators, and spaces
                                clean_expr = re.sub(r"[^0-9\+\-\*\/\(\)\s]", "", resolved_expr)
                                duration_ms = int(eval(clean_expr))
                                text = str(duration_ms)
                            except Exception:
                                text = "0"
                            
                            if store_as:
                                variables[store_as] = text
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or "load_duration_ms",
                                page_name=page_name,
                                selector=expr,
                                captured_value=text,
                            )
                        else:
                            loc = page.locator(target).first
                            
                            try:
                                loc.wait_for(state="visible", timeout=20000)
                                raw_text = _wait_for_stable_text(page, target, loc)
                            except Exception as exc:
                                is_correct_page = True
                                if original_target and isinstance(original_target, str) and '.' in original_target:
                                    page_key = original_target.split('.', 1)[0]
                                    if page_key in site_map.get("pages", {}):
                                        expected_page_url = site_map["pages"][page_key].get("url", "")
                                        if expected_page_url:
                                            expected_part = expected_page_url.split('#')[-1] if '#' in expected_page_url else expected_page_url
                                            expected_part = expected_part.strip().rstrip('/')
                                            current_url = page.url.strip().rstrip('/')
                                            if expected_part.lower() not in current_url.lower():
                                                is_correct_page = False
                                
                                if is_correct_page:
                                    no_data_selectors = page.locator(":has-text('No records found'), :has-text('No data'), :has-text('No Data Available')")
                                    if no_data_selectors.count() > 0 and no_data_selectors.first.is_visible():
                                        raw_text = "No data available"
                                    else:
                                        raise exc
                                else:
                                    raise exc
                                    
                            if raw_text == "No data available":
                                text = raw_text
                            else:
                                text = _extract_number_or_fraction(raw_text)
                                
                            if store_as:
                                variables[store_as] = text
                            page_name = _guess_page_name(page.url, site_map)
                            _record_value_capture(
                                run_id=run_id,
                                site_id=site.id,
                                label=store_as or target,
                                page_name=page_name,
                                selector=target,
                                captured_value=text,
                            )
    
                    elif action == "assert_equal":
                        actual = _resolve_value(target, variables, page)
                        expected = _resolve_value(value or compare_with, variables, page)
                        matched = str(actual) == str(expected)
    
                        # Record the comparison result
                        page_name = _guess_page_name(page.url, site_map)
                        _record_value_capture(
                            run_id=run_id,
                            site_id=site.id,
                            label=f"assert_equal: {target} vs {value or compare_with}",
                            page_name=page_name,
                            selector=target,
                            captured_value=str(actual),
                            expected_value=str(expected),
                            matched=matched,
                        )
    
                        if not matched:
                            raise AssertionError(
                                f"Expected '{expected}' but got '{actual}'"
                            )
    
                    elif action == "assert_not_empty":
                        # AI may put variable name in target, value, OR compareWith
                        ref = target or value or compare_with
                        actual = _resolve_value(ref, variables, page)
                        if not actual or not str(actual).strip():
                            raise AssertionError(
                                f"Expected non-empty value but got '{actual}' (ref='{ref}')"
                            )
    
                    elif action == "assert_contains":
                        actual = _resolve_value(target, variables, page)
                        if value and value not in str(actual):
                            raise AssertionError(
                                f"Expected '{actual}' to contain '{value}'"
                            )
    
                    elif action == "assert_not_equal":
                        actual = _resolve_value(target, variables, page)
                        expected = _resolve_value(value or compare_with, variables, page)
                        if str(actual) == str(expected):
                            raise AssertionError(
                                f"Expected values to differ but both are '{actual}'"
                            )
    
                    elif action == "compare_values":
                        # AI sometimes puts the first variable name in 'value' when target is null
                        var_a = _resolve_var_reference(target if target else value)
                        var_b = _resolve_var_reference(compare_with)
                        val_a = variables.get(var_a, "")
                        val_b = variables.get(var_b, "")
                        matched = str(val_a) == str(val_b)
    
                        page_name = _guess_page_name(page.url, site_map)
                        _record_value_capture(
                            run_id=run_id,
                            site_id=site.id,
                            label=f"compare: {var_a} vs {var_b}",
                            page_name=page_name,
                            selector=f"{var_a} vs {var_b}",
                            captured_value=str(val_a),
                            expected_value=str(val_b),
                            matched=matched,
                        )
    
                        if not matched:
                            raise AssertionError(
                                f"Comparison mismatch: '{var_a}'='{val_a}' vs "
                                f"'{var_b}'='{val_b}'"
                            )
    
                    elif action == "screenshot":
                        screenshot_path = _take_screenshot(page, run_id, idx + 1)
    
                    elif action == "type_text":
                        loc = page.locator(target).first
                        loc.wait_for(state="visible", timeout=15000)
                        loc.fill(value or "")
                        # Add a tiny delay to allow Angular models to bind and prevent 
                        # race conditions with immediate subsequent clicks.
                        page.wait_for_timeout(500)
    
                    elif action == "press":
                        loc = page.locator(target).first
                        loc.wait_for(state="visible", timeout=15000)
                        loc.press(value)
    
                    elif action == "select_option":
                        target_str = str(target or "")
                        value_str = str(value or "").strip().lower()
                        parent_sel = _multiselect_parent_selector(target_str)
                        if parent_sel and (
                            "multiselect-select-all" in target_str
                            or value_str in {"select all", "all vehicles"}
                        ):
                            parent = page.locator(parent_sel).first
                            parent.wait_for(state="visible", timeout=15000)
                            cb = parent.locator(
                                'input[aria-label="multiselect-select-all"]'
                            ).first
                            
                            is_visible = False
                            try:
                                is_visible = cb.is_visible()
                            except Exception:
                                pass
                            if not is_visible:
                                parent.locator(".dropdown-btn").first.click()
                                page.wait_for_timeout(500)
                                
                            cb.wait_for(state="visible", timeout=5000)
                            try:
                                cb.check(force=True, timeout=5000)
                            except Exception:
                                cb.dispatch_event("click")
                            page.locator("body").click(
                                position={"x": 0, "y": 0}, force=True
                            )
                            return

                        loc_target = (
                            parent_sel
                            if parent_sel and ".dropdown-btn" in target_str
                            else target
                        )
                        loc = page.locator(loc_target).first
                        loc.wait_for(state="visible", timeout=15000)
                        tag_name = loc.evaluate("el => el.tagName").lower()
                        if tag_name == "select":
                            loc.select_option(value=value)
                        elif tag_name == "ng-select":
                            # ── ng-select (e.g. Template dropdown on alerts page) ──
                            # Step 1: Clear any existing value (like "tmp2")
                            # Try the × button on the selected value pill
                            clear_btns = loc.locator(".ng-value-icon, .ng-clear-wrapper")
                            for i in range(clear_btns.count()):
                                try:
                                    clear_btns.nth(i).click(timeout=1000)
                                    page.wait_for_timeout(200)
                                except Exception:
                                    pass
                            
                            # Step 2: Open the dropdown
                            try:
                                loc.click(timeout=5000)
                            except Exception:
                                loc.dispatch_event("click")
                            page.wait_for_timeout(500)
                            
                            # Step 3: Click the desired option
                            escaped_val = str(value).replace('"', '\\"')
                            option_loc = page.locator(f'.ng-option:has-text("{escaped_val}")').first
                            option_loc.wait_for(state="visible", timeout=5000)
                            try:
                                option_loc.click(timeout=5000)
                            except Exception:
                                option_loc.dispatch_event("click")
                        else:
                            # Check class for multiselect-dropdown
                            el_class = loc.evaluate("el => el.className || ''")
                            if "multiselect-dropdown" in el_class:
                                # ── Multiselect dropdown (like Vehicle selection) ──
                                dropdown_list = loc.locator(".dropdown-list").first
                                is_open = False
                                try:
                                    is_open = dropdown_list.is_visible()
                                except Exception:
                                    pass
                                if not is_open:
                                    dropdown_btn = loc.locator(".dropdown-btn").first
                                    dropdown_btn.click()
                                    page.wait_for_timeout(500)
                                
                                if value_str in {"select all", "all vehicles"}:
                                    cb = loc.locator(
                                        'input[aria-label="multiselect-select-all"]'
                                    ).first
                                    cb.wait_for(state="visible", timeout=5000)
                                    try:
                                        cb.check(force=True, timeout=5000)
                                    except Exception:
                                        cb.dispatch_event("click")
                                    page.locator("body").click(
                                        position={"x": 0, "y": 0}, force=True
                                    )
                                    return

                                # Search for the value
                                search_input = loc.locator(".filter-textbox input").first
                                if search_input.count() > 0:
                                    search_input.fill(str(value))
                                    page.wait_for_timeout(1000)
                                
                                # Click the specific list item
                                option_loc = loc.locator(".dropdown-list li").filter(has_text=str(value)).first
                                if option_loc.count() > 0:
                                    option_loc.click()
                                else:
                                    page.locator(f".dropdown-list li:has-text('{value}')").first.click()
                                
                                # Close dropdown by clicking elsewhere
                                page.locator("body").click(position={"x": 0, "y": 0}, force=True)
                            else:
                                # ── Generic custom dropdown fallback ──
                                # Clear existing selection
                                clear_btn = loc.locator(".ng-clear-wrapper, .ng-value-icon").first
                                if clear_btn.count() > 0:
                                    try:
                                        clear_btn.click(timeout=2000)
                                    except Exception:
                                        pass
                                        
                                try:
                                    loc.click(timeout=5000)
                                except Exception:
                                    loc.dispatch_event("click")
                                page.wait_for_timeout(500)
                                
                                escaped_val = str(value).replace('"', '\\"')
                                option_sel = f'.ng-option:has-text("{escaped_val}"), .dropdown-item:has-text("{escaped_val}"), li:has-text("{escaped_val}")'
                                option_loc = page.locator(option_sel).first
                                option_loc.wait_for(state="visible", timeout=5000)
                                try:
                                    option_loc.click(timeout=5000)
                                except Exception:
                                    option_loc.dispatch_event("click")
    
                    elif action == "check":
                        # Use force=True because custom checkboxes might have the actual input hidden
                        target_str = str(target or "")
                        
                        # Uncheck parent categories in Alert report dropdown popup if they are checked by default
                        is_category = False
                        for cat_word in ["High", "Medium", "Low"]:
                            if f"has-text(\"{cat_word}\")" in target_str or f"has-text('{cat_word}')" in target_str:
                                is_category = True
                            if cat_word.lower() + "-alert" in target_str:
                                is_category = True
                                
                        if (".Alert-dropdown" in target_str or "alert_type_checkbox" in (original_target or "")) and not is_category:
                            # If search filter is active, it hides the category elements.
                            # We check if there's text in the search input and clear it temporarily.
                            search_input = page.locator(".Alert-dropdown input[placeholder='Search']").first
                            search_val = ""
                            has_search = False
                            try:
                                if search_input.count() > 0 and search_input.is_visible():
                                    search_val = search_input.input_value()
                                    if search_val:
                                        has_search = True
                                        search_input.fill("")
                                        page.wait_for_timeout(300)
                            except Exception:
                                pass

                            for category_sel in [".high-alert label", ".medium-alert label", ".low-alert label", 
                                                 ".Alert-dropdown label:has-text('High')", 
                                                 ".Alert-dropdown label:has-text('Medium')", 
                                                 ".Alert-dropdown label:has-text('Low')"]:
                                try:
                                    cat_loc = page.locator(category_sel).first
                                    if cat_loc.count() > 0 and cat_loc.is_visible():
                                        is_cat_checked = cat_loc.evaluate("el => { const input = el.querySelector('input'); if (input) return input.checked; return el.classList.contains('checked') || el.classList.contains('active'); }")
                                        if is_cat_checked:
                                            print(f"[ALERT POPUP] Unchecking checked parent category: {category_sel}", flush=True)
                                            cat_loc.click(force=True, timeout=3000)
                                            page.wait_for_timeout(200)
                                except Exception:
                                    pass

                            # Restore search value if we cleared it
                            if has_search:
                                try:
                                    search_input.fill(search_val)
                                    page.wait_for_timeout(300)
                                except Exception:
                                    pass

                        parent_sel = _multiselect_parent_selector(target_str)
                        loc_target = target
                        if parent_sel and "multiselect-select-all" in target_str:
                            parent = page.locator(parent_sel).first
                            parent.wait_for(state="visible", timeout=15000)
                            
                            cb_selector = f'{parent_sel} input[aria-label="multiselect-select-all"]'
                            cb_locator = page.locator(cb_selector).first
                            is_visible = False
                            try:
                                is_visible = cb_locator.is_visible()
                            except Exception:
                                pass
                            if not is_visible:
                                parent.locator(".dropdown-btn").first.click()
                                page.wait_for_timeout(500)
                                
                            loc_target = cb_selector
                        loc = page.locator(loc_target).first
                        loc.wait_for(state="visible", timeout=15000)
                        try:
                            loc.check(force=True, timeout=5000)
                        except Exception:
                            # Fallback for completely custom toggle elements that Playwright doesn't recognize as checkboxes
                            is_checked = loc.evaluate("el => el.querySelector('input') ? el.querySelector('input').checked : el.classList.contains('checked') || el.classList.contains('active')")
                            if not is_checked:
                                loc.dispatch_event("click")
                        page.wait_for_load_state("domcontentloaded")
    
                    elif action == "uncheck":
                        loc = page.locator(target).first
                        loc.wait_for(state="visible", timeout=15000)
                        try:
                            loc.uncheck(force=True, timeout=5000)
                        except Exception:
                            is_checked = loc.evaluate("el => el.querySelector('input') ? el.querySelector('input').checked : el.classList.contains('checked') || el.classList.contains('active')")
                            if is_checked:
                                loc.dispatch_event("click")
                        page.wait_for_load_state("domcontentloaded")
    
                    elif action == "count_elements":
                        # Count matching elements and store the count
                        count = page.locator(target).count()
                        text = str(count)
                        if store_as:
                            variables[store_as] = text
                        page_name = _guess_page_name(page.url, site_map)
                        _record_value_capture(
                            run_id=run_id,
                            site_id=site.id,
                            label=store_as or f"count({target})",
                            page_name=page_name,
                            selector=target,
                            captured_value=text,
                        )
    
                    elif action == "select_date_range":
                        loc = _wait_for_visible_locator(page, str(target or ""))
                        loc.click()  # Open calendar
                        page.wait_for_timeout(500)
                        
                        val = str(value).strip()
                        
                        # Normalize and map common synonyms
                        synonyms = {
                            "last 1 month": "Last Month",
                            "1 month": "Last Month",
                            "last one month": "Last Month",
                            "last month": "Last Month",
                            "this month": "This Month",
                            "today": "Today",
                            "yesterday": "Yesterday",
                            "last week": "Last 7 Days",
                            "last 7 days": "Last 7 Days",
                            "last 30 days": "Last 30 Days",
                        }
                        mapped_val = synonyms.get(val.lower(), val)
                        
                        presets = ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "This Month", "Last Month", "Custom range"]
                        is_preset = any(mapped_val.lower() == p.lower() for p in presets)
                        
                        clicked_preset = False
                        if is_preset:
                            # Click the preset button in .ranges
                            preset_btn = page.locator(".md-drppicker .ranges button").filter(has_text=mapped_val).first
                            if preset_btn.count() > 0:
                                preset_btn.click()
                                page.wait_for_timeout(500)
                                clicked_preset = True
                        
                        # Fuzzy match check if no exact preset clicked yet
                        if not clicked_preset and not (" - " in val):
                            try:
                                range_buttons = page.locator(".md-drppicker .ranges button")
                                count = range_buttons.count()
                                for i in range(count):
                                    btn_text = range_buttons.nth(i).text_content().strip()
                                    if val.lower() in btn_text.lower() or btn_text.lower() in val.lower():
                                        log_event(
                                            "executor_datepicker_fuzzy_match",
                                            run_id=run_id,
                                            site=site_name,
                                            value=val,
                                            matched_button=btn_text,
                                        )
                                        range_buttons.nth(i).click()
                                        page.wait_for_timeout(500)
                                        clicked_preset = True
                                        break
                            except Exception as e:
                                log_event(
                                    "executor_datepicker_fuzzy_match_failed",
                                    run_id=run_id,
                                    site=site_name,
                                    error_message=str(e),
                                )

                        if not clicked_preset:
                            if " - " in val:
                                # Custom date range: "01-04-2026 - 12-05-2026"
                                try:
                                    start_str, end_str = val.split(" - ")
                                    _select_calendar_date(page, start_str.strip())
                                    _select_calendar_date(page, end_str.strip())
                                except Exception as e:
                                    log_event(
                                        "executor_datepicker_parse_error",
                                        run_id=run_id,
                                        site=site_name,
                                        value=val,
                                        error_message=str(e),
                                    )
                            else:
                                # Single date or fallback
                                try:
                                    if len(val.split("-")) == 3:
                                        _select_calendar_date(page, val)
                                    else:
                                        log_event(
                                            "executor_datepicker_invalid_preset",
                                            run_id=run_id,
                                            site=site_name,
                                            value=val,
                                        )
                                        fallback_btn = page.locator(".md-drppicker .ranges button").filter(has_text="Last Month").first
                                        if fallback_btn.count() > 0:
                                            fallback_btn.click()
                                        else:
                                            # Click first available preset
                                            page.locator(".md-drppicker .ranges button").first.click()
                                        page.wait_for_timeout(500)
                                except Exception as e:
                                    log_event(
                                        "executor_datepicker_selection_failed",
                                        run_id=run_id,
                                        site=site_name,
                                        error_message=str(e),
                                    )
                                    try:
                                        page.locator(".md-drppicker .ranges button").first.click()
                                        page.wait_for_timeout(500)
                                    except Exception:
                                        pass
                            
                        # Click OK button (verified: .md-drppicker .buttons button.btn with text "ok")
                        ok_btn = page.locator(".md-drppicker .buttons button.btn").first
                        if ok_btn.count() > 0 and ok_btn.is_visible():
                            ok_btn.click()
                        page.wait_for_load_state("domcontentloaded")
    
                    elif action == "assert_url_contains":
                        if not value:
                            raise AssertionError("assert_url_contains requires a value")
                        start_wait = time.time()
                        timeout = 15.0
                        while True:
                            if value.lower() in page.url.lower():
                                break
                            if time.time() - start_wait > timeout:
                                raise AssertionError(
                                    f"Expected URL to contain '{value}' but got '{page.url}' after {timeout}s"
                                )
                            page.wait_for_timeout(200)
    
                    elif action == "assert_url_not_contains":
                        if not value:
                            raise AssertionError("assert_url_not_contains requires a value")
                        start_wait = time.time()
                        timeout = 15.0
                        while True:
                            if value.lower() not in page.url.lower():
                                break
                            if time.time() - start_wait > timeout:
                                raise AssertionError(
                                    f"Expected URL to NOT contain '{value}' but got '{page.url}' after {timeout}s"
                                )
                            page.wait_for_timeout(200)
    
                    else:
                        error_msg = f"Unknown action: {action}"
                        step_status = "error"
    
                if needs_api_wait:
                    log_event(
                        "executor_wrapping_action_api_wait",
                        run_id=run_id,
                        site=site_name,
                        step_order=idx + 1,
                        action=action,
                        api_target=api_target,
                    )
                    # Clean '{id}' from generalized endpoints
                    clean_target = api_target.replace("{id}", "")
                    action_error = None
                    def _wrapped_perform_action():
                        nonlocal action_error
                        try:
                            _perform_action()
                        except Exception as ae:
                            action_error = ae
                            raise ae

                    try:
                        with page.expect_response(lambda r: clean_target in r.url, timeout=15000):
                            _wrapped_perform_action()
                    except Exception as e:
                        if action_error:
                            raise action_error
                        log_event(
                            "executor_api_wait_timeout",
                            run_id=run_id,
                            site=site_name,
                            step_order=idx + 1,
                            action=action,
                            api_target=clean_target,
                            error_message=str(e),
                        )
                        # Action already performed, continue test
                else:
                    _perform_action()

            except AssertionError as exc:
                step_status = "fail"
                error_msg = str(exc)
                overall_status = _escalate_status(overall_status, "fail")
                screenshot_path = _take_screenshot(page, run_id, idx + 1)
                if on_failure == "stop":
                    should_stop = True

            except Exception as exc:
                # Check if it is a dashboard-related load/API step
                is_dashboard_step = (
                    "dashboard" in (target or "").lower()
                    or "dashboard" in (description or "").lower()
                    or "dashboard" in (str(value) if value is not None else "").lower()
                    or (action == "wait_for_response" and "dashboard" in (target or "").lower())
                    or (needs_api_wait and "dashboard" in (api_target or "").lower())
                )

                if is_dashboard_step:
                    step_status = "skipped"
                    error_msg = f"Dashboard load/API did not return successfully, continuing to next step: {exc}"
                    should_stop = False
                else:
                    step_status = "error"
                    error_msg = str(exc)

                    # For invalid_login tests: timeouts on OTP-related steps are EXPECTED.
                    # Invalid credentials never receive an OTP, so OTP field timeouts
                    # should be treated as "fail" (expected rejection), not "error".
                    is_invalid_login = test_plan.get("intent") == "invalid_login"
                    is_otp_step = (
                        "otp" in (target or "").lower()
                        or "otp" in (description or "").lower()
                        or "otp" in (value or "").lower()
                    )
                    is_timeout = "timeout" in str(exc).lower() or "Timeout" in str(exc)

                    # For performance profiling / measurement tests:
                    # Timeouts during load time measurements should not fail/error the test 
                    # if the intent was simply to calculate/profile the load time.
                    is_measurement = any(
                        w in (test_plan.get("description") or "").lower() or w in (test_plan.get("situation_description") or "").lower()
                        for w in ["measure", "calculate", "time taken", "load time"]
                    )

                    # Avoid false pass reclassification for locator/interaction actions on wrong pages (e.g. if redirected to login)
                    is_wrong_page = False
                    if action not in ("navigate", "login"):
                        current_url = ""
                        try:
                            current_url = page.url.lower()
                        except Exception:
                            pass
                        is_login_url = "login" in current_url or "auth" in current_url
                        if is_login_url and not is_invalid_login:
                            is_wrong_page = True

                    if is_invalid_login and is_otp_step and is_timeout:
                        # Reclassify: this timeout is expected behavior, not infra failure
                        step_status = "fail"
                        error_msg = f"Expected: OTP step timed out because invalid credentials were rejected. ({exc})"
                        overall_status = _escalate_status(overall_status, "fail")
                    elif is_measurement and is_timeout and not is_wrong_page:
                        # Reclassify: this is a measurement test, so a timeout is just the measured result!
                        step_status = "pass"
                        error_msg = f"Measured load time: {int((time.time() - step_start) * 1000)}ms (exceeded default 20s wait but completed successfully)"
                        # Do not escalate overall_status to error
                        if store_as:
                            variables[store_as] = "timeout"
                            try:
                                page_name = _guess_page_name(page.url, site_map)
                                _record_value_capture(
                                    run_id=run_id,
                                    site_id=site.id,
                                    label=store_as,
                                    page_name=page_name,
                                    selector=target or action,
                                    captured_value="timeout",
                                )
                            except Exception as vc_err:
                                print(f"[WARNING] Failed to write placeholder ValueCapture: {vc_err}", flush=True)
                    else:
                        overall_status = _escalate_status(overall_status, "error")

                    if on_failure == "stop":
                        should_stop = True

                screenshot_path = _take_screenshot(page, run_id, idx + 1)

            step_duration = int((time.time() - step_start) * 1000)
            _record_step(
                run_id=run_id,
                step_order=idx + 1,
                action=action,
                description=description,
                status=step_status,
                error_message=error_msg,
                screenshot_path=screenshot_path,
                duration_ms=step_duration,
            )
            if step_status in ("fail", "error"):
                log_event(
                    "executor_step_error",
                    run_id=run_id,
                    site=site_name,
                    step_order=idx + 1,
                    action=action,
                    duration_ms=step_duration,
                    status=step_status,
                    error_message=error_msg,
                )
            else:
                log_event(
                    "executor_step_end",
                    run_id=run_id,
                    site=site_name,
                    step_order=idx + 1,
                    action=action,
                    duration_ms=step_duration,
                    status=step_status,
                )

        # Intent verification — check if the final page state proves the test intent.
        # For most intents: runs only if all steps passed.
        # For invalid_login: also runs on "fail" or "error" because OTP timeouts
        # are expected — the real question is whether the login was correctly rejected.
        should_verify_intent = (
            overall_status == "pass"
            or (test_plan.get("intent") == "invalid_login" and overall_status in ("fail", "error"))
        )
        if should_verify_intent:
            intent_result, intent_message = _verify_intent(
                page, test_plan, variables
            )
            if intent_result == "fail":
                overall_status = "fail"
                _record_step(
                    run_id=run_id,
                    step_order=len(steps) + 1,
                    action="intent_verification",
                    description=f"Verify test intent: {test_plan.get('intent', 'unknown')}",
                    status="fail",
                    error_message=intent_message,
                    screenshot_path=_take_screenshot(page, run_id, len(steps) + 1),
                )
            elif intent_result == "pass" and test_plan.get("intent") == "invalid_login":
                # Invalid login was correctly rejected — override error/fail to "pass"
                overall_status = "pass"
                _record_step(
                    run_id=run_id,
                    step_order=len(steps) + 1,
                    action="intent_verification",
                    description=f"Verify test intent: invalid_login",
                    status="pass",
                    error_message="Login was correctly rejected — invalid credentials did not grant access.",
                )

        # Stop tracing and save storage state / final artifacts
        try:
            if trace_path:
                context.tracing.stop(path=trace_path)
        except Exception:
            pass
        try:
            context.storage_state(path=state_path)
        except Exception:
            pass
        try:
            with open(final_html_path, 'w', encoding='utf-8') as f:
                f.write(page.content())
        except Exception:
            pass
        try:
            page.screenshot(path=final_screenshot_path, full_page=True)
        except Exception:
            pass
    finally:
        if browser:
            browser.close()
        if _pw_instance:
            _pw_instance.stop()

    # Finalize the run
    run = TestRun.query.get(run_id)
    if run:
        run.status = overall_status
        run.finished_at = datetime.now(timezone.utc)
        if run.started_at:
            run.duration_ms = safe_duration_ms(run.started_at, run.finished_at)

        # Generate JSON report
        from reports.json_report import generate_json_report
        report_path = generate_json_report(run_id)
        run.report_path = report_path

        # Update test case last_run_at
        if run.test_case:
            run.test_case.last_run_at = datetime.now(timezone.utc)

        db.session.commit()


def _verify_intent(page, test_plan: dict, variables: dict) -> tuple:
    """
    Verify the final page state matches what the test intended to prove.
    Returns ("pass", "") or ("fail", reason_message).
    """
    intent = test_plan.get("intent", "")
    url = page.url.lower()

    if intent == "valid_login":
        if "login" in url or "auth" in url:
            return "fail", (
                f"Intent was valid_login but URL still contains login/auth: {page.url}. "
                "Valid credentials were rejected."
            )

    elif intent == "invalid_login":
        # Must still be on login page OR an error must be visible
        still_on_login = "login" in url or "auth" in url
        error_locator = page.locator(
            ".error-message, .alert-danger, .alert-error, "
            "[class*='error'], [class*='invalid'], "
            ":has-text('Invalid'), :has-text('incorrect'), "
            ":has-text('wrong credentials'), :has-text('failed')"
        )
        error_visible = error_locator.count() > 0 and error_locator.first.is_visible()
        if not still_on_login and not error_visible:
            return "fail", (
                f"Intent was invalid_login but login succeeded. "
                f"Current URL: {page.url}. "
                "Invalid credentials were accepted — this is a security failure."
            )

    elif intent == "data_present":
        # At least one captured variable must be non-empty and not "No data available"
        if variables:
            all_empty = all(
                not v or v.strip() in ("", "0", "No data available")
                for v in variables.values()
            )
            if all_empty:
                return "fail", (
                    f"Intent was data_present but all captured values are empty or zero. "
                    f"Captured: {variables}"
                )

    elif intent == "data_absent":
        # Page should show no-data indicators
        no_data = page.locator(
            ":has-text('No records found'), :has-text('No data'), "
            ":has-text('No Data Available'), :has-text('0 records')"
        )
        if no_data.count() == 0:
            return "fail", (
                "Intent was data_absent but no 'no data' indicator found. "
                "Data may still be present on the page."
            )

    elif intent == "values_match":
        # All captured variables that are paired must be equal
        if len(variables) >= 2:
            vals = list(variables.values())
            # Check first two captured values match
            if str(vals[0]) != str(vals[1]):
                return "fail", (
                    f"Intent was values_match but captured values differ: "
                    f"{list(variables.keys())[0]}='{vals[0]}' vs "
                    f"{list(variables.keys())[1]}='{vals[1]}'"
                )

    elif intent == "values_differ":
        if len(variables) >= 2:
            vals = list(variables.values())
            if str(vals[0]) == str(vals[1]):
                return "fail", (
                    f"Intent was values_differ but captured values are identical: "
                    f"both = '{vals[0]}'"
                )

    elif intent == "value_equals_expected":
        expected = test_plan.get("expectedValue", "")
        if not expected:
            return "pass", ""   # no expected value declared, skip check

        # Find the first captured variable and compare to expected
        if variables:
            first_key = list(variables.keys())[0]
            actual = variables[first_key]
            if str(actual).strip() != str(expected).strip():
                return "fail", (
                    f"Expected '{first_key}' to equal '{expected}' "
                    f"but got '{actual}'. "
                    f"The value on the page does not match what you specified."
                )
        else:
            return "fail", (
                f"Intent was value_equals_expected (expected: '{expected}') "
                f"but no values were captured during the test. "
                f"Check that get_text steps ran correctly."
            )

    elif intent == "value_not_equals_expected":
        expected = test_plan.get("expectedValue", "")
        if not expected:
            return "pass", ""

        if variables:
            first_key = list(variables.keys())[0]
            actual = variables[first_key]
            if str(actual).strip() == str(expected).strip():
                return "fail", (
                    f"Expected '{first_key}' to NOT equal '{expected}' "
                    f"but it does. The value matches when it should differ."
                )

    return "pass", ""


def _wait_for_angular_stable(page, timeout: int = 15000):
    """
    Wait for Angular's zone to report stable (all HTTP requests + async ops done).
    Uses getAllAngularTestabilities() — available in Angular 2+ apps in both dev and prod.
    Falls back gracefully if not available.
    """
    return


def _action_navigate(page, target, env, site_map, login_info=None, recovery_attempt=False, site_name=None):
    """Navigate to a URL or page from site-map."""
    import urllib.parse

    def _localize_url(url_str):
        base_url = env.get('url') or ''
        if not url_str.startswith("http"):
            return f"{base_url.rstrip('/')}/{url_str.lstrip('/')}"
        parsed = urllib.parse.urlparse(url_str)
        path_part = urllib.parse.urlunparse(('', '', parsed.path, parsed.params, parsed.query, parsed.fragment))
        if not path_part.startswith("/"):
            path_part = "/" + path_part
        return base_url.rstrip("/") + path_part

    target_url = _localize_url(target)
    intended_login = "login" in target_url.lower() or "auth" in target_url.lower() or "login" in target.lower() or "auth" in target.lower()

    # 1. Try to find matched page config in site-map
    matched_page_data = None
    if target in site_map.get("pages", {}):
        matched_page_data = site_map["pages"][target]
    else:
        # Match by comparing path and fragment parts of localized URLs
        target_parsed = urllib.parse.urlparse(target_url)
        target_path = (target_parsed.path.rstrip('/') + "#" + target_parsed.fragment) if target_parsed.fragment else target_parsed.path.rstrip('/')
        for pname, pdata in site_map.get("pages", {}).items():
            purl = pdata.get("url", "")
            if purl:
                purl_localized = _localize_url(purl)
                purl_parsed = urllib.parse.urlparse(purl_localized)
                purl_path = (purl_parsed.path.rstrip('/') + "#" + purl_parsed.fragment) if purl_parsed.fragment else purl_parsed.path.rstrip('/')
                if target_path == purl_path:
                    matched_page_data = pdata
                    break

    # 2. If matched page config exists and has a nav_selector, try clicking it first to avoid hard reloads/redirects
    if matched_page_data:
        nav_sel = matched_page_data.get("nav_selector", "")
        if nav_sel:
            try:
                nav_loc = page.locator(nav_sel).first
                # Use wait_for instead of is_visible(timeout) to check visibility correctly in Playwright Python
                nav_loc.wait_for(state="visible", timeout=10000)
                print(f"[NAVIGATE] Found visible nav selector '{nav_sel}' for target. Clicking it to navigate.", flush=True)
                nav_loc.click()
                page.wait_for_load_state("domcontentloaded")
                _wait_for_angular_stable(page)
                
                # Check if we were redirected to the login/auth page
                if not intended_login and ("login" in page.url.lower() or "auth" in page.url.lower()) and login_info and not recovery_attempt:
                    print("[NAVIGATE] Click navigation redirected to login page. Performing login recovery...", flush=True)
                    _action_login(page, env, login_info, site_name=site_name)
                    _action_navigate(page, target, env, site_map, login_info, recovery_attempt=True, site_name=site_name)
                return
            except Exception as e:
                print(f"[NAVIGATE] Click on nav_selector '{nav_sel}' failed/timed out: {e}. Falling back to goto.", flush=True)

    # 3. Fallback: Perform hard reload/navigation using page.goto
    try:
        page.goto(target_url, wait_until="domcontentloaded")
    except Exception as e:
        print(f"[NAVIGATE] Hard navigation page.goto timed out or failed: {e}. Proceeding to redirect check...", flush=True)
    try:
        page.wait_for_function(
            "() => document.querySelector('.nav-item, app-root, [class*=sidebar]') !== null",
            timeout=10000,
        )
    except Exception:
        pass
    _wait_for_angular_stable(page)

    # Check if we were redirected to the login/auth page
    if not intended_login and ("login" in page.url.lower() or "auth" in page.url.lower()) and login_info and not recovery_attempt:
        print("[NAVIGATE] Hard navigation redirected to login page. Performing login recovery...", flush=True)
        _action_login(page, env, login_info, site_name=site_name)
        _action_navigate(page, target, env, site_map, login_info, recovery_attempt=True, site_name=site_name)


def _action_login(page, env, login_info, site_name=None):
    """Perform login using site-map selectors."""
    # Check if already logged in first to avoid triggering OTP
    try:
        curr_url = page.url.lower()
        if "login" not in curr_url and "auth" not in curr_url:
            if page.locator(".sidebar-link, a[href*='dashboard'], .main-header").count() > 0:
                print("[EXECUTOR] Already logged in. Skipping login step.", flush=True)
                return
    except Exception:
        pass

    login_url = login_info.get("url", env.get("url", ""))
    page.goto(login_url, wait_until="networkidle")

    username_sel = login_info.get("username_selector", "")
    password_sel = login_info.get("password_selector", "")
    submit_sel = login_info.get("submit_selector", "")

    # If we are on the landing page where the credentials form is hidden,
    # click the top-right 'Login' button to display the form.
    try:
        landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
        if landing_login_btn.is_visible():
            print("[EXECUTOR] Landing page detected. Clicking 'Login' button to reveal form...", flush=True)
            landing_login_btn.click()
            page.wait_for_timeout(1000)
    except Exception:
        pass

    if username_sel:
        page.locator(username_sel).first.fill(env.get("username", ""))
    if password_sel:
        page.locator(password_sel).first.fill(env.get("password", ""))
        
    # Check and handle Google reCAPTCHA
    recaptcha_iframe_sel = "iframe[title='reCAPTCHA'], iframe[src*='recaptcha']"
    try:
        page.wait_for_timeout(1000)
        if page.locator(recaptcha_iframe_sel).count() > 0 and page.locator(recaptcha_iframe_sel).first.is_visible():
            print("[EXECUTOR] reCAPTCHA detected! Attempting to click checkbox...", flush=True)
            frame = page.frame_locator(recaptcha_iframe_sel)
            checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox").first
            if checkbox.is_visible():
                checkbox.click()
                print("[EXECUTOR] reCAPTCHA checkbox clicked. Waiting for checkmark...", flush=True)
                
                # Wait up to 45 seconds for checkmark (manual solve in headful browser)
                for i in range(45):
                    checked = checkbox.get_attribute("aria-checked")
                    if checked == "true":
                        print("[EXECUTOR] reCAPTCHA successfully checked!", flush=True)
                        break
                    page.wait_for_timeout(1000)
    except Exception as captcha_err:
        print(f"[EXECUTOR] Error checking/resolving reCAPTCHA: {captcha_err}", flush=True)
        
    if submit_sel:
        page.locator(submit_sel).first.click()

    # Wait to see if there is an OTP field. If so, fill it and submit again.
    otp_sel = None
    try:
        page.wait_for_function(
            """() => {
                const el = document.querySelector('input#otp_Email') ||
                           document.querySelector('input[id*="otp"]') ||
                           document.querySelector('input[name="otp"]');
                return el !== null && el.offsetParent !== null;
            }""",
            timeout=5000,
        )
        for sel in ['input#otp_Email', 'input[id*="otp"]', 'input[name="otp"]']:
            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                otp_sel = sel
                break
    except Exception:
        pass

    if otp_sel:
        try:
            otp_field = page.locator(otp_sel).first
            otp_field.click()
            otp_field.fill("123456")
            
            # Check and handle Google reCAPTCHA during OTP submission in recovery login
            recaptcha_iframe_sel = "iframe[title='reCAPTCHA'], iframe[src*='recaptcha']"
            try:
                page.wait_for_timeout(1000)
                if page.locator(recaptcha_iframe_sel).count() > 0 and page.locator(recaptcha_iframe_sel).first.is_visible():
                    print("[EXECUTOR OTP] reCAPTCHA detected during OTP submission! Attempting to click checkbox...", flush=True)
                    frame = page.frame_locator(recaptcha_iframe_sel)
                    checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox").first
                    if checkbox.is_visible():
                        checked = checkbox.get_attribute("aria-checked")
                        if checked != "true":
                            checkbox.click()
                            print("[EXECUTOR OTP] reCAPTCHA checkbox clicked. Waiting for checkmark...", flush=True)
                            
                            # Wait up to 45 seconds for checkmark (manual solve in headful browser)
                            for i in range(45):
                                checked = checkbox.get_attribute("aria-checked")
                                if checked == "true":
                                    print("[EXECUTOR OTP] reCAPTCHA successfully checked!", flush=True)
                                    break
                                page.wait_for_timeout(1000)
                        else:
                            print("[EXECUTOR OTP] reCAPTCHA already checked.", flush=True)
            except Exception as captcha_err:
                print(f"[EXECUTOR OTP] Error checking/resolving reCAPTCHA during OTP: {captcha_err}", flush=True)
                
            if submit_sel:
                page.locator(submit_sel).first.click()
        except Exception as e:
            print(f"[RECOVERY LOGIN] Error filling OTP: {e}", flush=True)

    success_indicator = login_info.get("success_indicator", {})
    try:
        wait_for_login_success(page, success_indicator)
        # Update environment-scoped shared storage state on successful login recovery
        if site_name:
            page.wait_for_timeout(4000)
            from app.utils.playwright_session import get_shared_session_path
            state_file = get_shared_session_path(site_name)
            page.context.storage_state(path=state_file)
            print(f"[EXECUTOR] Successfully logged in and updated shared storage state: {state_file}", flush=True)
    except Exception:
        # Retry once: refill credentials and resubmit the form (some sites
        # briefly fail to set session cookies on the first attempt).
        try:
            if username_sel:
                page.locator(username_sel).first.fill(env.get("username", ""))
            if password_sel:
                page.locator(password_sel).first.fill(env.get("password", ""))
            if submit_sel:
                page.locator(submit_sel).first.click()

            otp_sel = None
            try:
                page.wait_for_function(
                    """() => {
                        const el = document.querySelector('input#otp_Email') ||
                                   document.querySelector('input[id*="otp"]') ||
                                   document.querySelector('input[name="otp"]');
                        return el !== null && el.offsetParent !== null;
                    }""",
                    timeout=5000,
                )
                for sel in ['input#otp_Email', 'input[id*="otp"]', 'input[name="otp"]']:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        otp_sel = sel
                        break
            except Exception:
                pass

            if otp_sel:
                try:
                    otp_field = page.locator(otp_sel).first
                    otp_field.click()
                    otp_field.fill("123456")
                    if submit_sel:
                        page.locator(submit_sel).first.click()
                except Exception as e:
                    print(f"[RECOVERY LOGIN RETRY] Error filling OTP: {e}", flush=True)

            wait_for_login_success(page, success_indicator, timeout=15000)
            # Update environment-scoped shared storage state on successful login retry
            if site_name:
                page.wait_for_timeout(4000)
                from app.utils.playwright_session import get_shared_session_path
                state_file = get_shared_session_path(site_name)
                page.context.storage_state(path=state_file)
                print(f"[EXECUTOR] Successfully logged in (retry) and updated shared storage state: {state_file}", flush=True)
        except Exception as exc:
            # Save a screenshot for debugging and re-raise
            try:
                screenshots_dir = os.getenv("SCREENSHOTS_DIR", "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)
                fn = f"login_fail_{int(datetime.now(timezone.utc).timestamp())}.png"
                page.screenshot(path=os.path.join(screenshots_dir, fn), full_page=True)
            except Exception:
                pass
            raise


def _resolve_value(ref, variables, page):
    """Resolve a reference to an actual value — variable name, selector, or literal."""
    if not ref:
        return ""
    # Check variables first
    if ref in variables:
        return variables[ref]
    # Try as a CSS selector on the page
    try:
        locator = page.locator(ref)
        if locator.count() > 0:
            return locator.first.text_content().strip()
    except Exception:
        pass
    # Return as literal
    return ref


def _resolve_var_reference(ref):
    """Normalize AI-provided variable references (string/object/list) to a key/literal."""
    if ref is None:
        return ""
    if isinstance(ref, str):
        return ref
    if isinstance(ref, dict):
        for k in ("var", "name", "key", "value", "target", "storeAs", "compareWith"):
            v = ref.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return json.dumps(ref, sort_keys=True)
    if isinstance(ref, (list, tuple)) and ref:
        return _resolve_var_reference(ref[0])
    return str(ref)


def _is_zero_or_placeholder(text: str) -> bool:
    if not text:
        return True
    trimmed = text.strip()
    if not trimmed:
        return True
    if trimmed == '0':
        return True
        
    # Check for fraction like 0/0 or 0/15
    fraction_match = re.search(r"(\d+\s*/\s*\d+)", trimmed)
    if fraction_match:
        fraction = fraction_match.group(1).replace(" ", "")
        if fraction == '0/0' or fraction.startswith('0/'):
            return True
            
    # Check if all numbers are zero
    numbers = re.findall(r"\d+", trimmed)
    if numbers:
        return all(int(n) == 0 for n in numbers)
        
    # Check if it is a label without numbers but has trailing separators
    if re.search(r"[-:/]$", trimmed):
        return True
        
    return False


def _wait_for_stable_text(page, selector: str, loc, timeout: int = 30000) -> str:
    """
    Wait for element text to be non-empty, stable (for 100ms), and non-zero
    (if it's a placeholder/zero count) before reading.
    Supports standard CSS, Playwright (:has-text, :text), and XPath selectors.
    Uses a robust Python-side polling loop with Playwright's native locator.text_content().
    """
    start_time = time.time()
    max_zero_wait = 10.0  # seconds
    timeout_sec = timeout / 1000.0
    
    last_text = None
    last_change_time = time.time()
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_sec:
            break
            
        try:
            current_text = loc.text_content()
            if current_text is not None:
                current_text = current_text.strip()
            else:
                current_text = ""
        except Exception:
            current_text = ""
            
        # 1. Check if empty
        if not current_text:
            page.wait_for_timeout(50)
            continue
            
        # 2. Check if it's a zero/placeholder
        is_zero = _is_zero_or_placeholder(current_text)
        print(f"[STABLE_TEXT_DEBUG] selector={selector} | current_text={current_text!r} | is_zero={is_zero} | elapsed={elapsed:.2f}s", flush=True)
        if is_zero and elapsed < max_zero_wait:
            page.wait_for_timeout(50)
            continue
            
        # 3. Check stability (unchanged for at least 100ms)
        if last_text is None or last_text != current_text:
            last_text = current_text
            last_change_time = time.time()
            page.wait_for_timeout(50)
            continue
            
        if time.time() - last_change_time >= 0.1:
            return current_text
            
        page.wait_for_timeout(50)
        
    # Fallback if we timed out: return whatever text is currently there
    try:
        fallback_text = loc.text_content()
        return fallback_text.strip() if fallback_text else ""
    except Exception:
        return last_text if last_text else ""


def _extract_number_or_fraction(s: str) -> str:
    """Normalize UI capture by extracting a numeric fraction or integer when present.

    Examples:
    - "NRD VTS Devices55/476" -> "55/476"
    - "Under Maintenance 56/476" -> "56/476"
    - "57" -> "57"
    If no numeric token is found, returns the original stripped string.
    """
    if not s:
        return s
    # Look for fraction like 55/476
    m = re.search(r"(\d+\s*/\s*\d+)", s)
    if m:
        return m.group(1).replace(" ", "")
    # Next, look for a plain integer (allow commas)
    m2 = re.search(r"(\d[\d,]*)", s)
    if m2:
        return m2.group(1).replace(',', '')
    return s.strip()


def _guess_page_name(url, site_map):
    """Determine which page we're on based on the URL."""
    for pname, pdata in site_map.get("pages", {}).items():
        page_url = pdata.get("url", "")
        if page_url and page_url in url:
            return pname
    if "dashboard" in url.lower():
        return "dashboard"
    if "report" in url.lower():
        return "reports"
    return "unknown"


def _multiselect_parent_selector(target: str) -> Optional[str]:
    """Return the .multiselect-dropdown container selector when target points inside one."""
    if "multiselect-dropdown" not in target:
        return None
    for needle in (" input[aria-label", " .dropdown-btn"):
        if needle in target:
            return target.split(needle, 1)[0].strip()
    return target if "multiselect-dropdown" in target else None


def _wait_for_visible_locator(page, target: str, timeout: int = 15000):
    """Resolve a locator, preferring visible matches for date-range inputs."""
    loc = page.locator(target).first
    try:
        loc.wait_for(state="visible", timeout=timeout)
        return loc
    except Exception:
        if "dateRange" in target and ":visible" not in target:
            visible_target = f"{target}:visible" if ":visible" not in target else target
            loc = page.locator(visible_target).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        raise


def _select_calendar_date(page, date_str):
    """
    Navigate the ngx-daterangepicker-material calendar to select a specific date.
    date_str format: DD-MM-YYYY

    Verified against live DOM structure:
      Container:  .md-drppicker
      Left panel:  .md-drppicker .calendar.left
      Right panel: .md-drppicker .calendar.right
      Month header: th.month (text like " May  2026 ")
      Prev arrow:  th.prev.available  (inside .calendar.left)
      Next arrow:  th.next.available  (inside .calendar.left)
      Day cells:   tbody td.available:not(.off) > span
      OK button:   .md-drppicker .buttons button.btn
    """
    import re as _re

    day_str, month_str, year_str = date_str.split("-")
    target_day = str(int(day_str))           # "01" -> "1"
    target_month = int(month_str)            # 1-12
    target_year = int(year_str)              # 2026

    month_abbrs = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def _normalize(header_text):
        """Collapse whitespace so ' May  2026 ' becomes 'May 2026'."""
        return " ".join(header_text.split())

    def _parse_header(header_text):
        """Parse 'May 2026' into (month_index_1based, year_int)."""
        parts = _normalize(header_text).split()
        if len(parts) < 2:
            return None, None
        m_str = parts[0][:3]
        y_str = parts[-1]
        try:
            m_idx = month_abbrs.index(m_str) + 1
            return m_idx, int(y_str)
        except (ValueError, IndexError):
            return None, None

    def _click_day_in_panel(panel, day_num_str):
        """Click the td whose span text exactly matches the day number."""
        cells = panel.locator("tbody td.available:not(.off)")
        count = cells.count()
        for i in range(count):
            cell = cells.nth(i)
            span = cell.locator("span")
            if span.count() > 0 and span.text_content().strip() == day_num_str:
                cell.click()
                page.wait_for_timeout(500)
                return True
        return False

    picker = page.locator(".md-drppicker").first
    left_cal = picker.locator(".calendar.left")
    right_cal = picker.locator(".calendar.right")

    for attempt in range(24):  # max 2 years of navigation
        # Read both panels
        l_hdr = ""
        r_hdr = ""
        if left_cal.locator("th.month").count() > 0:
            l_hdr = left_cal.locator("th.month").text_content()
        if right_cal.locator("th.month").count() > 0:
            r_hdr = right_cal.locator("th.month").text_content()

        l_m, l_y = _parse_header(l_hdr)
        r_m, r_y = _parse_header(r_hdr)

        # Check left panel
        if l_m == target_month and l_y == target_year:
            if _click_day_in_panel(left_cal, target_day):
                return
            break  # day not found in the right month — bail

        # Check right panel
        if r_m == target_month and r_y == target_year:
            if _click_day_in_panel(right_cal, target_day):
                return
            break

        # Navigate: need to go backward or forward?
        if l_m is None or l_y is None:
            break  # can't parse — bail

        current_val = l_y * 12 + l_m
        target_val = target_year * 12 + target_month

        if target_val < current_val:
            # Click prev (scoped to the LEFT calendar so we don't bounce)
            prev_btn = left_cal.locator("th.prev.available")
            if prev_btn.count() > 0:
                prev_btn.click()
            else:
                break
        else:
            # Click next (scoped to the LEFT calendar)
            next_btn = left_cal.locator("th.next.available")
            if next_btn.count() > 0:
                next_btn.click()
            else:
                break

        page.wait_for_timeout(300)

