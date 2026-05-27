import os
import queue
import threading
import sys
import traceback
import time
from datetime import datetime, timezone
from db import db
from db.models import TestRun, SuiteRun, RunStep, safe_duration_ms
from playwright.sync_api import sync_playwright
from crawler.mapper import load_site_map, get_login_info
from runner.executor import _execute_for_site_with_page
from app.logging_config import log_event


TERMINAL_STATUSES = {"pass", "fail", "error", "cancelled"}


def _compute_suite_status(child_runs):
    statuses = [(run.status or "").lower() for run in child_runs]
    if not statuses:
        return "error"
    if any(status == "running" for status in statuses):
        return "running"
    if any(status == "queued" for status in statuses):
        return "queued"
    if all(status == "pass" for status in statuses):
        return "pass"
    if all(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "fail" for status in statuses):
        return "fail"
    if all(status in TERMINAL_STATUSES for status in statuses):
        return "partial"
    return "running"


def execute_suite_queue(app, tasks, suite_run_id, max_workers=5, jhs_credentials=None):
    """
    Execute tasks in a bounded worker queue.
    
    tasks: list of dicts: {"test_plan": ..., "site_name": ..., "run_id": ...}
    max_workers: integer number of parallel browsers to maintain
    jhs_credentials: dict of custom overrides for JHS portal credentials
    """
    suite_start = time.time()
    q = queue.Queue()
    for task in tasks:
        q.put(task)

    site_map = load_site_map()
    login_info = get_login_info(site_map)
    
    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

    def worker():
        # Start one Playwright and browser per worker thread
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless_env)
            
            while not q.empty():
                try:
                    task = q.get_nowait()
                except queue.Empty:
                    break
                
                run_id = task["run_id"]
                site_name = task["site_name"]
                test_plan = task["test_plan"]
                
                run_start = time.time()
                log_event(
                    "worker_task_start",
                    run_id=run_id,
                    suite_run_id=suite_run_id,
                    site=site_name,
                    worker_id=threading.current_thread().name,
                )
                
                from app.routes.runner import _active_runs
                _active_runs[str(run_id)] = threading.current_thread()
                
                try:
                    with app.app_context():
                        run = TestRun.query.get(run_id)
                        if run and run.status == "cancelled":
                            # Task was cancelled while in queue
                            continue
                        
                        # Check if parent suite run is cancel_requested or cancelled
                        if suite_run_id:
                            suite_run = SuiteRun.query.get(suite_run_id)
                            if suite_run and suite_run.status in ("cancel_requested", "cancelled"):
                                log_event(
                                    "worker_task_skipped",
                                    run_id=run_id,
                                    suite_run_id=suite_run_id,
                                    site=site_name,
                                    status="cancelled",
                                    message="Parent SuiteRun is cancelled"
                                )
                                if run:
                                    run.status = "cancelled"
                                    run.finished_at = datetime.now(timezone.utc)
                                    db.session.commit()
                                continue

                        if run and run.status == "queued":
                            run.status = "running"
                            db.session.commit()

                    state_file = "captures/jhs_state.json"
                    if os.path.exists(state_file):
                        print(f"[QUEUE EXECUTOR] Loading JHS storage state from {state_file}...", flush=True)
                        context = browser.new_context(viewport={"width": 1920, "height": 1080}, storage_state=state_file)
                    else:
                        print("[QUEUE EXECUTOR] No JHS storage state file found. Starting fresh context.", flush=True)
                        context = browser.new_context(viewport={"width": 1920, "height": 1080})
                    
                    # Prepare tracing for the context
                    captures_dir = os.getenv("CAPTURES_DIR", "captures")
                    os.makedirs(captures_dir, exist_ok=True)
                    try:
                        context.tracing.start(screenshots=True, snapshots=True, sources=True)
                    except Exception:
                        try:
                            context.tracing.start(screenshots=True, snapshots=True)
                        except Exception:
                            pass
                            
                    page = context.new_page()
                    
                    with app.app_context():
                        _execute_for_site_with_page(test_plan, site_name, run_id, site_map, login_info, page, context, jhs_credentials=jhs_credentials)
                        
                    run_duration = int((time.time() - run_start) * 1000)
                    log_event(
                        "worker_task_end",
                        run_id=run_id,
                        suite_run_id=suite_run_id,
                        site=site_name,
                        duration_ms=run_duration,
                        status="pass",
                    )
                except Exception as exc:
                    run_duration = int((time.time() - run_start) * 1000)
                    log_event(
                        "worker_task_error",
                        run_id=run_id,
                        suite_run_id=suite_run_id,
                        site=site_name,
                        duration_ms=run_duration,
                        status="error",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                    
                    with app.app_context():
                        try:
                            run = TestRun.query.get(run_id)
                            if run and run.status in ("queued", "running"):
                                run.status = "error"
                                run.finished_at = datetime.now(timezone.utc)
                                if run.started_at:
                                    run.duration_ms = safe_duration_ms(run.started_at, run.finished_at)
                                db.session.commit()
                        except Exception:
                            pass
                            
                        try:
                            step = RunStep(
                                run_id=run_id,
                                step_order=9999,
                                action="error",
                                description="Queue worker failed to execute task",
                                status="error",
                                error_message=str(exc),
                            )
                            db.session.add(step)
                            db.session.commit()
                        except Exception:
                            pass
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
                    
                    q.task_done()
                    
                    # Unregister from active runs if we added it there
                    from app.routes.runner import _active_runs
                    _active_runs.pop(str(run_id), None)
            
            # Browser and playwright automatically close when exiting 'with' block
            try:
                browser.close()
            except Exception:
                pass

    threads = []
    # Only spawn as many workers as there are tasks (up to max_workers)
    actual_workers = min(max_workers, len(tasks))
    
    log_event(
        "suite_dispatch_start",
        suite_run_id=suite_run_id,
        worker_count=actual_workers,
        task_count=len(tasks),
    )
    
    for _ in range(actual_workers):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
        
    # Queue is complete. Mark suite based on child run outcomes.
    with app.app_context():
        try:
            suite_run = SuiteRun.query.get(suite_run_id)
            if suite_run:
                child_runs = suite_run.test_runs.all()
                if child_runs:
                    finished_candidates = [r.finished_at for r in child_runs if r.finished_at]
                    if finished_candidates:
                        suite_run.finished_at = max(finished_candidates)
                    if suite_run.started_at and suite_run.finished_at:
                        suite_run.duration_ms = safe_duration_ms(suite_run.started_at, suite_run.finished_at)
                
                if suite_run.status == "cancel_requested":
                    suite_run.status = "cancelled"
                elif suite_run.status in ("queued", "running"):
                    suite_run.status = _compute_suite_status(child_runs)
                db.session.commit()
            
            suite_duration = int((time.time() - suite_start) * 1000)
            log_event(
                "suite_dispatch_end",
                suite_run_id=suite_run_id,
                duration_ms=suite_duration,
            )
        except Exception as e:
            log_event(
                "suite_dispatch_error",
                suite_run_id=suite_run_id,
                error_type=e.__class__.__name__,
                error_message=str(e),
            )
