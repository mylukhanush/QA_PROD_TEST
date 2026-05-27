#!/usr/bin/env python3
"""Run user-provided test plan for jhs83 and print step results.
Saves a TestCase and TestRun to the DB so steps are recorded.
"""
import os
import uuid
import json
from datetime import datetime, timezone

# Test plan (exactly as provided)
plan = {
  "category": "data_presence",
  "description": "This test logs into the application, navigates to the Dashboard and Device Health Dashboard pages, and verifies that key 'Not Reporting' (NRD) and other device health metrics are present and display non-empty values.",
  "expectedOutcome": "All specified NRD and device health metrics are present and display non-empty values on the Dashboard and Device Health Dashboard pages.",
  "failureMessage": "One or more NRD or device health metric values were not found or were empty on the Dashboard or Device Health Dashboard pages.",
  "runParallel": False,
  "steps": [
    {
      "action": "navigate",
      "compareWith": None,
      "description": "Navigate to jhs83 login page",
      "id": "step_1",
      "onFailure": "stop",
      "storeAs": None,
      "target": "http://103.123.173.50:8070/#/auth/login",
      "value": None
    },
    {
      "action": "type_text",
      "compareWith": None,
      "description": "Enter username",
      "id": "step_2",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "input[type='text'], input[name='username'], input[placeholder*='ser'], input.form-control",
      "value": "ranjit@assettl.com"
    },
    {
      "action": "type_text",
      "compareWith": None,
      "description": "Enter password",
      "id": "step_3",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "input[type='password'], input[name='password']",
      "value": "Rjil@12345"
    },
    {
      "action": "click",
      "compareWith": None,
      "description": "Click Send OTP button",
      "id": "step_4",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "button.login_btn",
      "value": None
    },
    {
      "action": "type_text",
      "compareWith": None,
      "description": "Enter OTP (hardcoded 123456)",
      "id": "step_5",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "input#otp_Email",
      "value": "123456"
    },
    {
      "action": "click",
      "compareWith": None,
      "description": "Click Login button to submit OTP",
      "id": "step_6",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "button.login_btn",
      "value": None
    },
    {
      "action": "wait_for_element",
      "compareWith": None,
      "description": "Wait for dashboard/sidebar to confirm login success",
      "id": "step_7",
      "onFailure": "stop",
      "storeAs": None,
      "target": ".sidebar-link, a[href*='dashboard'], .nav-link:has-text('Live'), .nav-link:has-text('Reports')",
      "value": None
    },
    {
      "action": "navigate",
      "compareWith": None,
      "description": "Navigate to Dashboard page",
      "id": "step_8",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "http://103.123.173.50:8070/#/pages/dashboard/aggregate-dashboard",
      "value": None
    },
    {
      "action": "wait_for_element",
      "compareWith": None,
      "description": "Wait for 'Vehicle Status' heading on Dashboard to load",
      "id": "step_9",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "h3:has-text(\"Vehicle Status\")",
      "value": None
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Not Reporting' count from Dashboard",
      "id": "step_10",
      "onFailure": "screenshot",
      "storeAs": "notReportingCount",
      "target": "div.status-card:has-text(\"Not Reporting\") div.status-count",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Not Reporting' count is not empty",
      "id": "step_11",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "notReportingCount"
    },
    {
      "action": "navigate",
      "compareWith": None,
      "description": "Navigate to Live page",
      "id": "step_11b",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "http://103.123.173.50:8070/#/pages/tracking/tracking-summary",
      "value": None
    },
    {
      "action": "wait_for_element",
      "compareWith": None,
      "description": "Wait for Live top cards to load",
      "id": "step_11c",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "div.status-card",
      "value": None
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Not Reporting' count from Live page",
      "id": "step_11d",
      "onFailure": "screenshot",
      "storeAs": "liveNotReportingCount",
      "target": "div.status-card:has-text(\"Not Reporting\") div.status-count",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert Live 'Not Reporting' count is not empty",
      "id": "step_11e",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "liveNotReportingCount"
    },
    {
      "action": "navigate",
      "compareWith": None,
      "description": "Navigate to Device Health Dashboard page",
      "id": "step_12",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "http://103.123.173.50:8070/#/pages/nrddashboard/nrd-dashboard",
      "value": None
    },
    {
      "action": "wait_for_element",
      "compareWith": None,
      "description": "Wait for 'Response Time' heading on Device Health Dashboard to load",
      "id": "step_13",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": "h4:has-text(\"Response Time\")",
      "value": None
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'NRD VTS Devices' metric value",
      "id": "step_14",
      "onFailure": "screenshot",
      "storeAs": "nrdVtsDevicesValue",
      "target": "h4:has-text(\"NRD VTS Devices\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'NRD VTS Devices' metric value is not empty",
      "id": "step_15",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "nrdVtsDevicesValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Probable Wiring Issues' metric value",
      "id": "step_16",
      "onFailure": "screenshot",
      "storeAs": "probableWiringIssuesValue",
      "target": "h4:has-text(\"Probable Wiring Issues\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Probable Wiring Issues' metric value is not empty",
      "id": "step_17",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "probableWiringIssuesValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Under Maintenance' metric value",
      "id": "step_18",
      "onFailure": "screenshot",
      "storeAs": "underMaintenanceValue",
      "target": "h4:has-text(\"Under Maintenance\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Under Maintenance' metric value is not empty",
      "id": "step_19",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "underMaintenanceValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Camera Inactive' metric value",
      "id": "step_20",
      "onFailure": "screenshot",
      "storeAs": "cameraInactiveValue",
      "target": "h4:has-text(\"Camera Inactive 2/7\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Camera Inactive' metric value is not empty",
      "id": "step_21",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "cameraInactiveValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Camera Under Maintenance' metric value",
      "id": "step_22",
      "onFailure": "screenshot",
      "storeAs": "cameraUnderMaintenanceValue",
      "target": "h4:has-text(\"Camera Under Maintenance 2/7\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Camera Under Maintenance' metric value is not empty",
      "id": "step_23",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "cameraUnderMaintenanceValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Camera Obstruction Alert' metric value",
      "id": "step_24",
      "onFailure": "screenshot",
      "storeAs": "cameraObstructionAlertValue",
      "target": "h4:has-text(\"Camera Obstruction Alert-/-\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Camera Obstruction Alert' metric value is not empty",
      "id": "step_25",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "cameraObstructionAlertValue"
    },
    {
      "action": "store_value",
      "compareWith": None,
      "description": "Store 'Voicebox Tampering Alerts' metric value",
      "id": "step_26",
      "onFailure": "screenshot",
      "storeAs": "voiceboxTamperingAlertsValue",
      "target": "h4:has-text(\"Voicebox Tampering Alerts-/-\")",
      "value": None
    },
    {
      "action": "assert_not_empty",
      "compareWith": None,
      "description": "Assert 'Voicebox Tampering Alerts' metric value is not empty",
      "id": "step_27",
      "onFailure": "screenshot",
      "storeAs": None,
      "target": None,
      "value": "voiceboxTamperingAlertsValue"
    }
  ],
  "targetSites": [
    "jhs83"
  ],
  "testName": "Verify NRD and Device Health Metrics Data Presence"
}

if __name__ == '__main__':
    # Ensure environment variables for DB and site creds
    os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:root@localhost:5432/qa_automation')
    os.environ.setdefault('FLASK_SECRET_KEY', 'qa-agent-secret-key-2026')
    os.environ.setdefault('JHS83_URL', 'http://103.123.173.50:8070')
    os.environ.setdefault('JHS83_USERNAME', 'ranjit@assettl.com')
    os.environ.setdefault('JHS83_PASSWORD', 'Rjil@12345')

    from app import create_app
    from db import db
    from db.models import TestCase, TestRun, Site
    from runner.executor import execute_test_plan

    app = create_app()
    with app.app_context():
        site = Site.query.filter_by(name='jhs83').first()
        if not site:
            print('Site jhs83 not found in DB. Run seed-sites or add site. Aborting.')
            raise SystemExit(1)

        # Create TestCase
        tc = TestCase(
            id=str(uuid.uuid4()),
            situation_description=plan.get('description', 'user plan'),
            category=plan.get('category', 'custom'),
            steps=plan.get('steps', []),
        )
        db.session.add(tc)
        db.session.commit()

        run_id = str(uuid.uuid4())
        tr = TestRun(
            id=run_id,
            test_case_id=tc.id,
            site_id=site.id,
            triggered_by='cli',
        )
        db.session.add(tr)
        db.session.commit()

        print('Starting execution for run_id=', run_id)
        execute_test_plan(plan, {'jhs83': run_id})

        # Print run steps
        steps = []
        from db.models import RunStep
        steps = RunStep.query.filter_by(run_id=run_id).order_by(RunStep.step_order).all()
        print('\nRun steps:')
        for s in steps:
            print(f"#{s.step_order} {s.action} -> {s.status} {('ERROR:'+s.error_message) if s.error_message else ''}")

        run = TestRun.query.get(run_id)
        print('\nRun final status:', run.status)
        print('Run report path:', run.report_path)
