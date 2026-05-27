#!/usr/bin/env python3
"""Run a minimal test plan through the executor to smoke-test login flows.
"""
import os
import uuid
from runner.executor import execute_test_plan
from app import create_app

os.environ.setdefault('JHS82_URL', 'http://103.123.173.50:8090')
os.environ.setdefault('JHS82_USERNAME', 'ranjit@assettl.com')
os.environ.setdefault('JHS82_PASSWORD', 'Rjil@12345')

plan = {
    "steps": [
        {"action": "navigate", "target": os.environ['JHS82_URL']},
        {"action": "login", "target": ""},
        {"action": "wait_for_element", "target": "#"},
    ]
}

run_id = str(uuid.uuid4())
run_ids = {"jhs82": run_id}

app = create_app()
with app.app_context():
    # Ensure there's a TestCase and TestRun so DB FKs are satisfied
    from db.models import TestCase, TestRun, Site
    from db import db

    site = Site.query.filter_by(name='jhs82').first()
    if not site:
        raise RuntimeError('Site jhs82 not present in DB. Seed sites first.')

    tc = TestCase(
        id=str(uuid.uuid4()),
        situation_description='Smoke executor test',
        category='smoke',
        steps=[step for step in plan['steps']],
    )
    db.session.add(tc)
    db.session.commit()

    tr = TestRun(
        id=run_id,
        test_case_id=tc.id,
        site_id=site.id,
        triggered_by='cli',
    )
    db.session.add(tr)
    db.session.commit()

    print('Running smoke executor plan, run_id=', run_id)
    execute_test_plan(plan, run_ids)
    print('Done')
