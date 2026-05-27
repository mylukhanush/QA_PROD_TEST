"""
Crawler routes — trigger and monitor site crawling.
"""
import threading
import uuid
from flask import Blueprint, render_template, jsonify, current_app

from db import db
from db.models import Site, SiteElement

crawler_bp = Blueprint("crawler", __name__)

# In-memory crawl job tracker
_crawl_jobs = {}


@crawler_bp.route("/crawl")
def crawl_page():
    """Render the crawl management page."""
    sites = Site.query.filter_by(is_active=True).all()
    element_count = SiteElement.query.count()
    last_element = SiteElement.query.order_by(SiteElement.last_crawled_at.desc()).first()
    last_crawl_time = last_element.last_crawled_at if last_element else None
    return render_template(
        "crawl.html",
        sites=sites,
        element_count=element_count,
        last_crawl_time=last_crawl_time,
    )


@crawler_bp.route("/api/crawl", methods=["POST"])
def api_start_crawl():
    """Start a crawler run in a background thread."""
    from flask import request, session
    site_name = request.json.get("site", "jhs82")
    job_id = str(uuid.uuid4())

    jhs_creds = {
        "username": session.get("jhs_username"),
        "password": session.get("jhs_password")
    }

    _crawl_jobs[job_id] = {
        "status": "running",
        "site": site_name,
        "progress": 0,
        "message": "Starting crawler…",
        "elements_found": 0,
    }

    def _run_crawl(app, jid, sname, jhs_creds_override):
        with app.app_context():
            try:
                from crawler.extractor import crawl_site
                result = crawl_site(
                    sname,
                    progress_callback=lambda p, m: _crawl_jobs[jid].update(
                        {"progress": p, "message": m}
                    ),
                    jhs_credentials=jhs_creds_override,
                )
                _crawl_jobs[jid].update({
                    "status": "done",
                    "progress": 100,
                    "message": "Crawl complete",
                    "elements_found": result.get("elements_found", 0),
                })
            except Exception as exc:
                _crawl_jobs[jid].update({
                    "status": "error",
                    "message": str(exc),
                })

    t = threading.Thread(
        target=_run_crawl,
        args=(current_app._get_current_object(), job_id, site_name, jhs_creds),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job_id})


@crawler_bp.route("/api/crawl/<job_id>/progress")
def api_crawl_progress(job_id):
    """Return current crawl progress for HTMX polling."""
    job = _crawl_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)
