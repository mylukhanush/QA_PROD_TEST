"""
Results routes - run history list and run detail page.
"""
import os

from flask import Blueprint, abort, current_app, render_template, request, send_from_directory, url_for

from db import db
from db.models import Site, TestRun, RunStep, ValueCapture, TestCase, TestSuite, safe_duration_ms
from app.routes.runner import _is_run_actively_running

results_bp = Blueprint("results", __name__)

TERMINAL_RUN_STATUSES = {"pass", "fail", "error", "cancelled"}


def _compute_suite_status(child_runs):
    statuses = [(run.status or "").lower() for run in child_runs]
    if not statuses:
        return "error"
    if any(status == "cancel_requested" for status in statuses):
        return "cancel_requested"
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
    if all(status in TERMINAL_RUN_STATUSES for status in statuses):
        return "partial"
    return "running"


def _screenshot_filename(path):
    """Return the screenshot filename from a DB path stored with either slash style."""
    if not path:
        return None
    return path.replace("\\", "/").split("/")[-1]


@results_bp.route("/screenshots/<path:filename>")
def screenshot_file(filename):
    """Serve captured failure screenshots from the configured screenshots directory."""
    safe_filename = _screenshot_filename(filename)
    if not safe_filename:
        abort(404)
    screenshot_dir = os.path.abspath(current_app.config["SCREENSHOTS_DIR"])
    return send_from_directory(screenshot_dir, safe_filename)


@results_bp.route("/runs")
def runs_list():
    """Redesigned history page focusing on Test Suites."""
    from db.models import TestSuite, SuiteRun
    from sqlalchemy import func
    from datetime import datetime
    
    # Fetch all suites
    suites = TestSuite.query.order_by(TestSuite.name).all()
    
    # Fetch recent suite runs
    date_filter = request.args.get("date")
    status_filter = request.args.get("status")
    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            s_query = SuiteRun.query.filter(func.date(SuiteRun.started_at) == target_date)
            if status_filter:
                s_query = s_query.filter(SuiteRun.status == status_filter)
            suite_runs = s_query.order_by(SuiteRun.started_at.desc()).all()
        except Exception:
            suite_runs = SuiteRun.query.order_by(SuiteRun.started_at.desc()).limit(50).all()
    else:
        s_query = SuiteRun.query
        if status_filter:
            s_query = s_query.filter(SuiteRun.status == status_filter)
        suite_runs = s_query.order_by(SuiteRun.started_at.desc()).limit(50).all()

    suite_run_updates = False
    for sr in suite_runs:
        child_runs = sr.test_runs.all()
        if not child_runs:
            sr.ui_status = sr.status
            continue

        computed_status = _compute_suite_status(child_runs)
        if sr.status in ("cancel_requested", "cancelled"):
            sr.ui_status = sr.status
        else:
            sr.ui_status = computed_status

        if computed_status != "running" and computed_status != "cancel_requested" and (sr.status or "").lower() in ("queued", "running", "completed"):
            sr.status = computed_status
            finished_candidates = [r.finished_at for r in child_runs if r.finished_at]
            if finished_candidates:
                sr.finished_at = max(finished_candidates)
            if sr.started_at and sr.finished_at:
                sr.duration_ms = safe_duration_ms(sr.started_at, sr.finished_at)
            suite_run_updates = True

    if suite_run_updates:
        db.session.commit()
    
    # Individual runs (legacy/backup view)
    site_filter = request.args.get("site")
    status_filter = request.args.get("status")
    query = (
        TestRun.query
        .filter(TestRun.suite_run_id.is_(None))  # Show only individually-triggered runs
        .order_by(TestRun.started_at.desc())
    )
    if site_filter:
        site = Site.query.filter_by(name=site_filter).first()
        if site: query = query.filter_by(site_id=site.id)
    if status_filter: query = query.filter_by(status=status_filter)
    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            query = query.filter(func.date(TestRun.started_at) == target_date)
        except Exception:
            pass
    
    runs = query.limit(50).all()
    for run in runs:
        run.is_stale_running = run.status == "running" and not _is_run_actively_running(run)

    sites = Site.query.filter_by(is_active=True).all()
    return render_template(
        "runs.html",
        suites=suites,
        suite_runs=suite_runs,
        runs=runs,
        sites=sites,
        site_filter=site_filter,
        status_filter=status_filter,
        date_filter=date_filter
    )


@results_bp.route("/test-cases")
def test_cases_list():
    """List test cases that are not assigned to any suite."""
    unassigned_test_cases = (
        TestCase.query
        .filter(~TestCase.suites.any())
        .order_by(TestCase.created_at.desc())
        .all()
    )
    suites = TestSuite.query.order_by(TestSuite.name).all()
    return render_template(
        "test_cases.html",
        test_cases=unassigned_test_cases,
        suites=suites,
    )


@results_bp.route("/runs/<run_id>")
def run_detail(run_id):
    """Detailed view of a single test run."""
    run = TestRun.query.get_or_404(run_id)
    steps = RunStep.query.filter_by(run_id=run.id).order_by(RunStep.step_order).all()
    captures = ValueCapture.query.filter_by(run_id=run.id).all()
    sites = (
        Site.query
        .filter(Site.name.in_(["jhs81", "jhs82", "jhs83", "jhs84"]), Site.is_active.is_(True))
        .order_by(Site.name)
        .all()
    )
    screenshot_dir = os.path.abspath(current_app.config["SCREENSHOTS_DIR"])
    for step in steps:
        filename = _screenshot_filename(step.screenshot_path)



        step.screenshot_filename = filename
        step.screenshot_url = url_for("results.screenshot_file", filename=filename) if filename else None
        step.screenshot_exists = (
            bool(filename) and os.path.exists(os.path.join(screenshot_dir, filename))
        )

    test_case = run.test_case
    prompt_text = ""
    test_plan_json = {}

    if test_case:
        prompt_text = test_case.user_prompt or test_case.situation_description
        test_plan_json = test_case.test_plan or {
            "description": test_case.situation_description,
            "category": test_case.category,
            "steps": test_case.steps,
        }

    total_steps_duration_ms = sum(s.duration_ms for s in steps if s.duration_ms is not None)

    return render_template(
        "run_detail.html",
        run=run,
        steps=steps,
        captures=captures,
        sites=sites,
        prompt_text=prompt_text,
        test_plan_json=test_plan_json,
        total_steps_duration_ms=total_steps_duration_ms,
    )


@results_bp.route("/logs")
def system_logs_page():
    """Renders the system log viewer page."""
    return render_template("logs.html")


@results_bp.route("/api/logs")
def api_get_logs():
    """API endpoint to fetch the latest 100 log lines from instance/app.log."""
    from app.logging_config import LOG_FILE_PATH
    import json
    
    if not os.path.exists(LOG_FILE_PATH):
        return {"logs": []}
        
    logs = []
    try:
        with open(LOG_FILE_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-100:]:
                if line.strip():
                    try:
                        logs.append(json.loads(line.strip()))
                    except:
                        logs.append({
                            "timestamp": "",
                            "level": "INFO",
                            "logger": "root",
                            "message": line.strip()
                        })
    except Exception as e:
        return {"error": str(e)}, 500
        
    return {"logs": list(reversed(logs))}


@results_bp.route("/kpi")
def kpi_sheet():
    """KPI Sheet page showing performance analytics."""
    return render_template("kpi.html")


