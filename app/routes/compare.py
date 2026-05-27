"""
Compare routes — cross-site comparison of test results.
"""
from flask import Blueprint, render_template, request, jsonify

from db import db
from db.models import Site, TestCase, TestRun, ValueCapture

compare_bp = Blueprint("compare", __name__)


@compare_bp.route("/compare")
def compare_page():
    """Cross-site comparison page."""
    test_cases = TestCase.query.order_by(TestCase.created_at.desc()).limit(50).all()
    sites = Site.query.filter_by(is_active=True).all()
    return render_template("compare.html", test_cases=test_cases, sites=sites)


@compare_bp.route("/api/compare", methods=["POST"])
def api_compare():
    """
    Run or retrieve a cross-site comparison for a given test case.
    Returns value captures per site in a comparison grid.
    """
    data = request.json
    test_case_id = data.get("test_case_id")
    if not test_case_id:
        return jsonify({"error": "test_case_id required"}), 400

    # Get the most recent run per site for this test case
    sites = Site.query.filter_by(is_active=True).all()
    comparison = []

    for site in sites:
        run = (
            TestRun.query
            .filter_by(test_case_id=test_case_id, site_id=site.id)
            .order_by(TestRun.started_at.desc())
            .first()
        )
        if not run:
            comparison.append({
                "site": site.name,
                "status": "not_run",
                "captures": [],
            })
            continue

        captures = ValueCapture.query.filter_by(run_id=run.id).all()
        comparison.append({
            "site": site.name,
            "status": run.status,
            "run_id": str(run.id),
            "captures": [
                {
                    "label": c.label,
                    "page": c.page,
                    "captured_value": c.captured_value,
                    "expected_value": c.expected_value,
                    "matched": c.matched,
                }
                for c in captures
            ],
        })

    return jsonify({"comparison": comparison})
