from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, current_app
from db import db
from db.models import TestCase, TestSuite, SuiteRun, TestRun, Site, safe_duration_ms
import uuid

suites_bp = Blueprint("suites", __name__)

@suites_bp.route("/api/suites", methods=["GET"])
def list_suites():
    suites = TestSuite.query.order_by(TestSuite.name).all()
    return jsonify([{
        "id": str(s.id),
        "name": s.name,
        "description": s.description,
        "test_cases_count": len(s.test_cases)
    } for s in suites])

@suites_bp.route("/api/suites/<suite_id>", methods=["GET"])
def get_suite(suite_id):
    suite = TestSuite.query.get_or_404(suite_id)
    return jsonify({
        "id": str(suite.id),
        "name": suite.name,
        "description": suite.description,
        "test_cases": [{
            "id": str(tc.id),
            "name": tc.name,
            "situation_description": tc.situation_description,
            "category": tc.category
        } for tc in suite.test_cases]
    })

@suites_bp.route("/api/test-cases/<tc_id>", methods=["GET"])
def get_test_case(tc_id):
    tc = TestCase.query.get_or_404(tc_id)
    return jsonify({
        "id": str(tc.id),
        "name": tc.name,
        "situation_description": tc.situation_description,
        "category": tc.category,
        "test_plan": tc.test_plan,
        "steps": tc.steps,
        "created_at": tc.created_at.strftime('%b %d, %Y %H:%M') if tc.created_at else None
    })

@suites_bp.route("/api/test-cases/<tc_id>/site-runs", methods=["GET"])
def get_test_case_site_runs(tc_id):
    """Return latest run per site for a test case, newest first."""
    tc = TestCase.query.get_or_404(tc_id)
    runs = (
        TestRun.query
        .filter_by(test_case_id=tc.id)
        .order_by(TestRun.started_at.desc())
        .all()
    )

    latest_by_site = {}
    ordered = []
    for run in runs:
        site_name = run.site.name if run.site else None
        if not site_name or site_name in latest_by_site:
            continue
        payload = {
            "site": site_name,
            "run_id": str(run.id),
            "status": run.status,
            "started_at": run.started_at.strftime('%b %d, %Y %H:%M') if run.started_at else None,
        }
        latest_by_site[site_name] = payload
        ordered.append(payload)

    return jsonify({
        "test_case_id": str(tc.id),
        "sites": ordered
    })

@suites_bp.route("/api/suites", methods=["POST"])
def create_suite():
    data = request.json
    name = data.get("name")
    if not name:
        return jsonify({"error": "Suite name is required"}), 400
    
    suite = TestSuite(name=name, description=data.get("description"))
    db.session.add(suite)
    db.session.commit()
    return jsonify({"id": str(suite.id), "name": suite.name})

@suites_bp.route("/api/suites/<suite_id>", methods=["PUT"])
def update_suite(suite_id):
    suite = TestSuite.query.get_or_404(suite_id)
    data = request.json or {}

    name = (data.get("name") or "").strip()
    description = data.get("description")

    if not name:
        return jsonify({"error": "Suite name is required"}), 400

    existing = TestSuite.query.filter(TestSuite.name == name, TestSuite.id != suite.id).first()
    if existing:
        return jsonify({"error": "Suite name already exists"}), 400

    suite.name = name
    suite.description = description
    db.session.commit()
    return jsonify({
        "id": str(suite.id),
        "name": suite.name,
        "description": suite.description
    })

@suites_bp.route("/api/suites/<suite_id>", methods=["DELETE"])
def delete_suite(suite_id):
    suite = TestSuite.query.get_or_404(suite_id)

    # Remove suite references from historical runs before deleting suite runs.
    suite_runs = SuiteRun.query.filter_by(suite_id=suite.id).all()
    suite_run_ids = [sr.id for sr in suite_runs]
    if suite_run_ids:
        TestRun.query.filter(TestRun.suite_run_id.in_(suite_run_ids)).update(
            {"suite_run_id": None}, synchronize_session=False
        )
        for sr in suite_runs:
            db.session.delete(sr)

    suite.test_cases = []
    db.session.delete(suite)
    db.session.commit()
    return jsonify({"status": "deleted", "id": suite_id})

@suites_bp.route("/api/test-cases/<tc_id>/save-to-suite", methods=["POST"])
def save_to_suite(tc_id):
    data = request.json
    tc_name = (data.get("name") or "").strip()
    suite_id = data.get("suite_id")
    new_suite_name = (data.get("new_suite_name") or "").strip()
    target_sites = data.get("target_sites") or data.get("targetSites") or []

    test_case = TestCase.query.get_or_404(tc_id)
    if tc_name:
        test_case.name = tc_name
    existing_plan = test_case.test_plan if isinstance(test_case.test_plan, dict) else {}
    if isinstance(target_sites, list):
        normalized_sites = [str(s).strip() for s in target_sites if str(s).strip()]
        if normalized_sites:
            # Normalize site scope key so suite execution can consistently read it.
            existing_plan["target_sites"] = normalized_sites
            existing_plan["targetSites"] = normalized_sites
            test_case.test_plan = existing_plan
    elif existing_plan:
        # Backfill from older camelCase plans when save payload did not include target sites.
        existing_targets = existing_plan.get("target_sites") or existing_plan.get("targetSites") or []
        normalized_sites = [str(s).strip() for s in existing_targets if str(s).strip()]
        if normalized_sites:
            existing_plan["target_sites"] = normalized_sites
            existing_plan["targetSites"] = normalized_sites
            test_case.test_plan = existing_plan

    if new_suite_name:
        suite = TestSuite.query.filter_by(name=new_suite_name).first()
        if suite is None:
            suite = TestSuite(name=new_suite_name)
            db.session.add(suite)
            db.session.flush()
    elif suite_id:
        suite = TestSuite.query.get(suite_id)
        if suite is None:
            return jsonify({"error": "Selected suite was not found"}), 404
    else:
        db.session.commit()
        return jsonify({"status": "updated", "id": str(test_case.id)})

    if suite and test_case not in suite.test_cases:
        suite.test_cases.append(test_case)
    
    db.session.commit()
    return jsonify({"status": "saved", "id": str(test_case.id), "suite_id": str(suite.id) if suite else None})


@suites_bp.route("/api/test-cases/bulk-save-to-suite", methods=["POST"])
def bulk_save_to_suite():
    data = request.json or {}
    test_case_ids = data.get("test_case_ids") or []
    suite_id = data.get("suite_id")
    new_suite_name = (data.get("new_suite_name") or "").strip()

    if not test_case_ids or not isinstance(test_case_ids, list):
        return jsonify({"error": "test_case_ids must be a non-empty list"}), 400

    if new_suite_name:
        suite = TestSuite.query.filter_by(name=new_suite_name).first()
        if suite is None:
            suite = TestSuite(name=new_suite_name)
            db.session.add(suite)
            db.session.flush()
    elif suite_id:
        suite = TestSuite.query.get(suite_id)
        if suite is None:
            return jsonify({"error": "Selected suite was not found"}), 404
    else:
        return jsonify({"error": "suite_id or new_suite_name is required"}), 400

    test_cases = TestCase.query.filter(TestCase.id.in_(test_case_ids)).all()
    if not test_cases:
        return jsonify({"error": "No valid test cases found"}), 404

    assigned_count = 0
    for test_case in test_cases:
        if test_case not in suite.test_cases:
            suite.test_cases.append(test_case)
            assigned_count += 1

    db.session.commit()
    return jsonify({
        "status": "saved",
        "suite_id": str(suite.id),
        "requested_count": len(test_case_ids),
        "found_count": len(test_cases),
        "assigned_count": assigned_count
    })

@suites_bp.route("/api/suites/<suite_id>/run", methods=["POST"])
def run_suite(suite_id):
    suite = TestSuite.query.get_or_404(suite_id)
    if not suite.test_cases:
        return jsonify({"error": "This suite has no test cases"}), 400
    active_sites = Site.query.filter_by(is_active=True).all()
    if not active_sites:
        return jsonify({"error": "No active sites available"}), 400

    # Create a SuiteRun record
    suite_run = SuiteRun(suite_id=suite.id, status="queued")
    db.session.add(suite_run)
    db.session.commit()

    total_runs = 0
    used_sites = set()

    for tc in suite.test_cases:
        test_plan = tc.test_plan or {
            "description": tc.situation_description,
            "category": tc.category,
            "steps": tc.steps or [],
        }

        # Site selection priority per test case:
        # 1) Explicit target_sites saved with the test case
        # 2) Historical run sites for the test case
        # 3) All active sites (fallback)
        target_site_names = []
        if isinstance(tc.test_plan, dict):
            raw_sites = tc.test_plan.get("target_sites") or tc.test_plan.get("targetSites") or []
            if isinstance(raw_sites, list):
                target_site_names = [str(s).strip() for s in raw_sites if str(s).strip()]

        sites = []
        if target_site_names:
            allowed = set(target_site_names)
            sites = [s for s in active_sites if s.name in allowed]

        historical_site_ids = {
            r.site_id for r in tc.test_runs if r.site_id is not None
        }
        if not sites and historical_site_ids:
            sites = [s for s in active_sites if s.id in historical_site_ids]
        if not sites:
            sites = active_sites

        for site in sites:
            tr = TestRun(
                test_case_id=tc.id,
                site_id=site.id,
                suite_run_id=suite_run.id,
                triggered_by="web",
                status="queued",
            )
            db.session.add(tr)
            db.session.flush()

            total_runs += 1
            used_sites.add(site.name)

    db.session.commit()

    if total_runs == 0:
        suite_run.status = "error"
        suite_run.finished_at = datetime.now(timezone.utc)
        suite_run.duration_ms = 0
        db.session.commit()
        return jsonify({
            "error": "No eligible active site runs found for suite test cases."
        }), 400

    queued_runs = TestRun.query.filter_by(suite_run_id=suite_run.id, status="queued").all()
    try:
        from runner.queue_executor import execute_suite_queue
        import threading
        import os
        from flask import current_app
        
        queued_tasks = []
        for run in queued_runs:
            test_plan = run.test_case.test_plan or {
                "description": run.test_case.situation_description,
                "category": run.test_case.category,
                "steps": run.test_case.steps or [],
            }
            queued_tasks.append({
                "test_plan": test_plan,
                "site_name": run.site.name,
                "run_id": str(run.id),
            })
            
        from flask import session
        jhs_creds = {
            "username": session.get("jhs_username"),
            "password": session.get("jhs_password")
        }
        max_workers = int(os.getenv("MAX_SUITE_WORKERS", "5"))
        app_obj = current_app._get_current_object()
        threading.Thread(
            target=execute_suite_queue,
            args=(app_obj, queued_tasks, str(suite_run.id), max_workers, jhs_creds),
            daemon=True
        ).start()
    except Exception as exc:
        suite_run.status = "error"
        suite_run.finished_at = datetime.now(timezone.utc)
        suite_run.duration_ms = safe_duration_ms(suite_run.started_at, suite_run.finished_at)
        db.session.commit()
        return jsonify({
            "error": f"Failed to enqueue suite runs: {exc}"
        }), 500

    return jsonify({
        "status": "queued",
        "suite_run_id": str(suite_run.id),
        "queued_count": total_runs,
        "message": f"Queued {total_runs} test runs across {len(used_sites)} sites."
    })

@suites_bp.route("/api/test-cases/<tc_id>/run", methods=["POST"])
def run_single_test_case(tc_id):
    test_case = TestCase.query.get_or_404(tc_id)
    active_sites = Site.query.filter_by(is_active=True).all()
    if not active_sites:
        return jsonify({"error": "No active sites available"}), 400

    test_plan = test_case.test_plan or {
        "description": test_case.situation_description,
        "category": test_case.category,
        "steps": test_case.steps or [],
    }

    # Site selection priority (same logic as suite runner):
    # 1) Explicit target_sites saved in the test plan
    # 2) Historical run sites for this test case
    # 3) All active sites (fallback)
    target_site_names = []
    if isinstance(test_case.test_plan, dict):
        raw_sites = test_case.test_plan.get("target_sites") or test_case.test_plan.get("targetSites") or []
        if isinstance(raw_sites, list):
            target_site_names = [str(s).strip() for s in raw_sites if str(s).strip()]

    sites = []
    if target_site_names:
        allowed = set(target_site_names)
        sites = [s for s in active_sites if s.name in allowed]

    if not sites:
        historical_site_ids = {
            r.site_id for r in test_case.test_runs if r.site_id is not None
        }
        if historical_site_ids:
            sites = [s for s in active_sites if s.id in historical_site_ids]

    if not sites:
        sites = active_sites

    run_ids = {}
    for site in sites:
        tr = TestRun(
            test_case_id=test_case.id,
            site_id=site.id,
            triggered_by="web",
            status="running",
        )
        db.session.add(tr)
        db.session.flush()
        run_ids[site.name] = str(tr.id)

    db.session.commit()

    from flask import session
    jhs_creds = {
        "username": session.get("jhs_username"),
        "password": session.get("jhs_password")
    }
    from app.routes.runner import _launch_run_execution
    _launch_run_execution(current_app._get_current_object(), test_plan, run_ids, jhs_credentials=jhs_creds)

    return jsonify({
        "status": "triggered",
        "test_case_id": str(test_case.id),
        "run_ids": run_ids,
        "message": f"Triggered {len(run_ids)} run(s) for test case."
    })

@suites_bp.route("/api/suites/<suite_id>/test-cases/<tc_id>", methods=["DELETE"])
def remove_test_case_from_suite(suite_id, tc_id):
    suite = TestSuite.query.get_or_404(suite_id)
    test_case = TestCase.query.get_or_404(tc_id)

    if test_case in suite.test_cases:
        suite.test_cases.remove(test_case)
        db.session.commit()
        return jsonify({"status": "removed", "suite_id": suite_id, "test_case_id": tc_id})

    return jsonify({"error": "Test case not found in suite"}), 404


@suites_bp.route("/api/test-cases/<tc_id>", methods=["DELETE"])
def delete_test_case(tc_id):
    """Delete a test case and all of its dependent runs if none are actively running."""
    from app.routes.runner import _delete_run_record, _is_run_actively_running

    test_case = TestCase.query.get_or_404(tc_id)
    runs = list(test_case.test_runs)

    for run in runs:
        if _is_run_actively_running(run):
            return jsonify({"error": "Cannot delete a test case while one of its runs is still active"}), 400

    for suite in list(test_case.suites):
        suite.test_cases.remove(test_case)

    for run in runs:
        _delete_run_record(run)

    db.session.delete(test_case)
    db.session.commit()
    return jsonify({"status": "deleted", "id": str(test_case.id)})


@suites_bp.route("/api/test-cases/bulk-delete", methods=["POST"])
def bulk_delete_test_cases():
    """Delete multiple test cases if none of their runs are currently active."""
    from app.routes.runner import _delete_run_record, _is_run_actively_running

    data = request.json or {}
    test_case_ids = data.get("test_case_ids") or []
    if not test_case_ids or not isinstance(test_case_ids, list):
        return jsonify({"error": "test_case_ids must be a non-empty list"}), 400

    test_cases = TestCase.query.filter(TestCase.id.in_(test_case_ids)).all()
    if not test_cases:
        return jsonify({"error": "No valid test cases found"}), 404

    for test_case in test_cases:
        for run in list(test_case.test_runs):
            if _is_run_actively_running(run):
                return jsonify({
                    "error": f"Cannot delete test case '{test_case.name or str(test_case.id)}' while one of its runs is still active"
                }), 400

    deleted_ids = []
    for test_case in test_cases:
        runs = list(test_case.test_runs)
        for suite in list(test_case.suites):
            suite.test_cases.remove(test_case)
        for run in runs:
            _delete_run_record(run)
        deleted_ids.append(str(test_case.id))
        db.session.delete(test_case)

    db.session.commit()
    return jsonify({
        "status": "deleted",
        "deleted_ids": deleted_ids,
        "deleted_count": len(deleted_ids),
        "requested_count": len(test_case_ids)
    })


@suites_bp.route("/api/suite-runs/<suite_run_id>/cancel", methods=["POST"])
def api_cancel_suite_run(suite_run_id):
    """Cancel a suite run and all its child runs."""
    suite_run = SuiteRun.query.get(suite_run_id)
    if not suite_run:
        return jsonify({"error": "Suite run not found"}), 404

    if suite_run.status in ("queued", "running"):
        suite_run.status = "cancel_requested"
        
        # All queued child runs become cancelled immediately
        queued_runs = TestRun.query.filter_by(suite_run_id=suite_run.id, status="queued").all()
        for run in queued_runs:
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc)

        # All running child runs become cancel_requested
        running_runs = TestRun.query.filter_by(suite_run_id=suite_run.id, status="running").all()
        for run in running_runs:
            run.status = "cancel_requested"

        db.session.commit()
        return jsonify({
            "message": "Suite run cancel requested. Queued runs cancelled immediately, running runs cancel requested.",
            "status": "cancel_requested"
        })
    else:
        return jsonify({"error": f"Cannot cancel suite run in status: {suite_run.status}"}), 400



