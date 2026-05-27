from datetime import datetime, timezone

from app.celery_app import celery_app
from db import db
from db.models import RunStep, SuiteRun, TestRun, safe_duration_ms
from runner.executor import execute_test_run

TERMINAL_STATUSES = {"pass", "fail", "error", "cancelled"}


def _compute_suite_status(child_runs):
    statuses = [(run.status or "").lower() for run in child_runs]
    if not statuses:
        return "error"
    if all(status == "pass" for status in statuses):
        return "pass"
    if all(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status in ("queued", "running") for status in statuses):
        return "running" if any(status == "running" for status in statuses) else "queued"
    if any(status == "cancelled" for status in statuses):
        return "partial"
    if any(status == "error" for status in statuses):
        return "error" if all(status == "error" for status in statuses) else "partial"
    if any(status == "fail" for status in statuses):
        return "fail"
    if all(status in TERMINAL_STATUSES for status in statuses):
        return "partial"
    return "error"


@celery_app.task(name="runner.execute_test_run_task")
def execute_test_run_task(run_id):
    run = TestRun.query.get(run_id)
    if not run:
        return {"run_id": str(run_id), "status": "missing"}

    # Check if run or parent suite run is cancelled / cancel requested
    if run.status in ("cancel_requested", "cancelled") or (run.suite_run and run.suite_run.status in ("cancel_requested", "cancelled")):
        run.status = "cancelled"
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        if run.suite_run_id:
            finalize_suite_run_task.delay(str(run.suite_run_id))
        return {"run_id": str(run_id), "status": "cancelled"}

    if run.status == "queued":
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        if run.suite_run and run.suite_run.status == "queued":
            run.suite_run.status = "running"
        db.session.commit()

    try:
        execute_test_run(str(run.id))
    except Exception as exc:
        db.session.rollback()
        failed_run = TestRun.query.get(run_id)
        if failed_run and failed_run.status in ("queued", "running"):
            failed_run.status = "error"
            failed_run.finished_at = datetime.now(timezone.utc)
            if failed_run.started_at:
                failed_run.duration_ms = safe_duration_ms(failed_run.started_at, failed_run.finished_at)
            step = RunStep(
                run_id=failed_run.id,
                step_order=9999,
                action="error",
                description="Celery task failed to execute test run",
                status="error",
                error_message=str(exc),
            )
            db.session.add(step)
            db.session.commit()
    finally:
        refreshed_run = TestRun.query.get(run_id)
        if refreshed_run and refreshed_run.suite_run_id:
            finalize_suite_run_task.delay(str(refreshed_run.suite_run_id))

    return {"run_id": str(run_id), "status": "completed"}


@celery_app.task(name="runner.finalize_suite_run_task")
def finalize_suite_run_task(suite_run_id):
    suite_run = SuiteRun.query.get(suite_run_id)
    if not suite_run:
        return {"suite_run_id": str(suite_run_id), "status": "missing"}

    child_runs = suite_run.test_runs.all()
    if not child_runs:
        suite_run.status = "error"
        suite_run.finished_at = datetime.now(timezone.utc)
        suite_run.duration_ms = 0
        db.session.commit()
        return {"suite_run_id": str(suite_run_id), "status": "error"}

    computed_status = _compute_suite_status(child_runs)
    
    all_terminal = all((run.status or "").lower() in TERMINAL_STATUSES for run in child_runs)
    
    if all_terminal and suite_run.status == "cancel_requested":
        suite_run.status = "cancelled"
    elif suite_run.status not in ("cancel_requested", "cancelled"):
        suite_run.status = computed_status

    if all_terminal:
        finished_candidates = [run.finished_at for run in child_runs if run.finished_at]
        suite_run.finished_at = max(finished_candidates) if finished_candidates else datetime.now(timezone.utc)
        if suite_run.started_at and suite_run.finished_at:
            suite_run.duration_ms = safe_duration_ms(suite_run.started_at, suite_run.finished_at)

    db.session.commit()
    return {"suite_run_id": str(suite_run_id), "status": suite_run.status}
