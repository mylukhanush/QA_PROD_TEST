"""
JSON report generator.

After every test run, generates a JSON report file saved to /reports/{run_id}.json.
"""
import json
import os
from datetime import datetime, timezone

from db import db
from db.models import TestRun, RunStep, ValueCapture


def generate_json_report(run_id: str) -> str:
    """
    Generate a JSON report for a completed test run.

    Parameters
    ----------
    run_id : str
        The UUID of the test run.

    Returns
    -------
    str — path to the generated report file.
    """
    run = TestRun.query.get(run_id)
    if not run:
        raise ValueError(f"Run {run_id} not found")

    steps = RunStep.query.filter_by(run_id=run.id).order_by(RunStep.step_order).all()
    captures = ValueCapture.query.filter_by(run_id=run.id).all()

    # Build summary message
    summary = _build_summary(run, steps, captures)

    # Collect screenshot paths
    screenshots = [s.screenshot_path for s in steps if s.screenshot_path]

    report = {
        "run_id": str(run.id),
        "test_name": run.test_case.situation_description if run.test_case else "",
        "category": run.test_case.category if run.test_case else "",
        "site": run.site.name if run.site else "",
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "steps": [
            {
                "step_order": s.step_order,
                "action": s.action,
                "description": s.description,
                "status": s.status,
                "error_message": s.error_message,
                "screenshot_path": s.screenshot_path,
                "executed_at": s.executed_at.isoformat() if s.executed_at else None,
            }
            for s in steps
        ],
        "value_captures": [
            {
                "label": c.label,
                "page": c.page,
                "selector": c.selector,
                "captured_value": c.captured_value,
                "expected_value": c.expected_value,
                "matched": c.matched,
                "captured_at": c.captured_at.isoformat() if c.captured_at else None,
            }
            for c in captures
        ],
        "screenshots": screenshots,
        "summary": summary,
    }

    # Save to file
    reports_dir = os.getenv("REPORTS_DIR", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.join(reports_dir, f"{run_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    return path


def _build_summary(run, steps, captures) -> str:
    """Build a plain English summary of the run."""
    total = len(steps)
    passed = sum(1 for s in steps if s.status == "pass")
    failed = sum(1 for s in steps if s.status == "fail")
    errors = sum(1 for s in steps if s.status == "error")
    site_name = run.site.name if run.site else "unknown"

    parts = [f"{passed}/{total} steps passed on {site_name}."]

    if failed:
        # Find the first failure
        for s in steps:
            if s.status == "fail" and s.error_message:
                parts.append(f"Failure: {s.error_message}")
                break

    if errors:
        parts.append(f"{errors} step(s) had errors.")

    # Value comparison summary
    mismatches = [c for c in captures if c.matched is False]
    if mismatches:
        for m in mismatches[:3]:
            parts.append(
                f"{m.label} on {m.page} showed '{m.captured_value}' "
                f"but expected '{m.expected_value}'. Mismatch detected on {site_name}."
            )

    if run.status == "pass":
        parts.append("All checks passed successfully.")

    return " ".join(parts)


def load_json_report(run_id: str) -> dict:
    """Load a previously generated JSON report from disk."""
    reports_dir = os.getenv("REPORTS_DIR", "reports")
    path = os.path.join(reports_dir, f"{run_id}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
