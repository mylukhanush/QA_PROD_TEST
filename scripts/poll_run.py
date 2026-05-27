"""Check the latest run status."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
app = create_app()

with app.app_context():
    from db import db
    from db.models import TestRun, ValueCapture
    run = TestRun.query.order_by(TestRun.started_at.desc()).first()
    print(f"Waiting for run {run.id} to finish...")
    
    retries = 0
    while run.status == 'running' and retries < 20:
        time.sleep(5)
        db.session.refresh(run)
        retries += 1
    
    print(f"Final Status: {run.status}")
    caps = ValueCapture.query.filter_by(run_id=run.id).all()
    for c in caps:
        print(f"Captured: {c.label} = {c.captured_value}")
