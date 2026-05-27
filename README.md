# QA Agent

Web-based QA automation system for generating, running, and reviewing test cases across multiple sites.

## Features
- Generate test plans from natural-language scenarios.
- Run test cases across selected sites (`jhs81`-`jhs84`).
- Save test cases into suites and run suite/group flows.
- View run-level details: steps, status, errors, screenshots, value captures.
- Compare cross-site values and track pass/fail/error history.

## Project Structure
```text
QA_agent/
|-- app/                    # Flask app package
|   |-- routes/             # HTTP routes (runner, results, suites, etc.)
|   |-- static/             # CSS/JS assets
|   `-- templates/          # Jinja templates
|-- ai/                     # Test plan prompt/generation logic
|-- crawler/                # Selector/site map extraction utilities
|-- db/
|   |-- migrations/         # Alembic migrations
|   `-- models.py           # SQLAlchemy models
|-- reports/                # JSON/terminal report generation
|-- runner/                 # Playwright executor and run orchestration
|-- scripts/                # Debug/probing/helper scripts
|-- run.py                  # Application entrypoint
|-- requirements.txt
`-- README.md
```

## Workflow
1. Configure environment
   - Create `.env` from `.env.example`.
   - Fill site credentials and base URLs for each site (`JHS81_*`, `JHS82_*`, etc.).

2. Install dependencies
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

3. Database setup
```bash
flask db upgrade
```

4. Start application
```bash
python run.py
```

## Celery + Redis Suite Workers
Suite execution now uses Celery tasks backed by Redis (instead of Flask in-memory threads).

1. Start Redis
```bash
redis-server
```

2. Start Celery worker
```bash
celery -A app.celery_app.celery_app worker --loglevel=INFO --concurrency=5
```

3. Start Flask app
```bash
flask run
```

Environment variables:
- `CELERY_BROKER_URL` (default `redis://localhost:6379/0`)
- `CELERY_RESULT_BACKEND` (default `redis://localhost:6379/1`)
- `PLAYWRIGHT_HEADLESS` (default `true`)
- `CELERY_WORKER_CONCURRENCY` or `MAX_SUITE_WORKERS` (default `5`)

5. Generate and run tests
   - Open `/run`.
   - Enter scenario.
   - Generate plan.
   - Select site(s) and execute.

6. Review results
   - Dashboard (`/`) shows date-wise execution summary.
   - `/runs` shows suites, suite history, and individual runs.
   - Open run details to inspect step-by-step execution and value captures.

7. Suite workflow
   - Save test case to suite.
   - Open suite details slide.
   - Run or remove individual test cases.
   - Use site chips to inspect site-specific details.
   - Use redirect icon to open exact individual run page.

## Notes
- Runtime artifacts (captures, screenshots, logs, temp files, local venvs) are ignored in git.
- Keep `site-map.json` regenerated via crawler flow when selectors change.
