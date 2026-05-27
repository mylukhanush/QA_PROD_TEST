"""
Parallel test runner.

When a test plan has runParallel=true and targets multiple sites,
this module launches one thread per site, each with its own
Playwright browser context.
"""
import threading
from typing import Dict

from runner.executor import _execute_for_site, _site_env
from crawler.mapper import load_site_map, get_login_info
from db import db
from db.models import Site, TestRun, safe_duration_ms
from datetime import datetime, timezone


def execute_parallel(test_plan: dict, run_ids: Dict[str, str]):
    """
    Execute test plan against multiple sites in parallel.

    Parameters
    ----------
    test_plan : dict
        The AI-generated test plan.
    run_ids : dict
        Mapping of site_name -> run_id.
    """
    site_map = load_site_map()
    login_info = site_map.get("login", {})

    threads = []
    errors = {}

    for site_name, run_id in run_ids.items():
        def _worker(sname, rid):
            try:
                _execute_for_site(test_plan, sname, rid, site_map, login_info)
            except Exception as exc:
                errors[sname] = str(exc)
                # Mark run as error
                run = TestRun.query.get(rid)
                if run:
                    run.status = "error"
                    run.finished_at = datetime.now(timezone.utc)
                    if run.started_at:
                        run.duration_ms = safe_duration_ms(run.started_at, run.finished_at)
                    db.session.commit()

        t = threading.Thread(target=_worker, args=(site_name, run_id), daemon=True)
        threads.append(t)

    # Start all threads
    for t in threads:
        t.start()

    # Wait for all to complete
    for t in threads:
        t.join()

    return errors
