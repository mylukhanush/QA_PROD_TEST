"""
History routes — value capture history over time for charting.
"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, jsonify

from db import db
from db.models import Site, SiteElement, ValueCapture

history_bp = Blueprint("history", __name__)


@history_bp.route("/history")
def history_page():
    """Value history page with charts."""
    sites = Site.query.filter_by(is_active=True).all()
    labels = (
        db.session.query(SiteElement.label)
        .distinct()
        .order_by(SiteElement.label)
        .all()
    )
    labels = [l[0] for l in labels]
    return render_template("history.html", sites=sites, labels=labels)


@history_bp.route("/api/history")
def api_history():
    """
    Value capture history with filters.
    Query params: label, site, days (default 7)
    """
    label = request.args.get("label")
    site_name = request.args.get("site")
    days = int(request.args.get("days", 7))

    if not label:
        return jsonify({"error": "label is required"}), 400

    since = datetime.now(timezone.utc) - timedelta(days=days)

    query = ValueCapture.query.filter(
        ValueCapture.label == label,
        ValueCapture.captured_at >= since,
    ).order_by(ValueCapture.captured_at)

    if site_name:
        site = Site.query.filter_by(name=site_name).first()
        if site:
            query = query.filter_by(site_id=site.id)

    captures = query.all()

    return jsonify({
        "label": label,
        "data": [
            {
                "site": c.site.name,
                "value": c.captured_value,
                "captured_at": c.captured_at.isoformat(),
            }
            for c in captures
        ],
    })


@history_bp.route("/api/elements")
def api_elements():
    """List all site elements (for dropdowns)."""
    elements = SiteElement.query.order_by(SiteElement.page, SiteElement.label).all()
    return jsonify([
        {
            "id": str(e.id),
            "page": e.page,
            "section": e.section,
            "label": e.label,
            "selector": e.selector,
            "element_type": e.element_type,
            "is_dynamic": e.is_dynamic,
            "value_sample": e.value_sample,
        }
        for e in elements
    ])
