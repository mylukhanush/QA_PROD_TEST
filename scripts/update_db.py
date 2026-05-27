import sys
import os
from dotenv import load_dotenv

# Add the project root to sys.path so we can import 'app' and 'db'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from app import create_app
from db import db
from db.models import * # Ensure all models are loaded
from sqlalchemy import text

def update_database():
    app = create_app()
    with app.app_context():
        print("Initializing new database tables...")
        try:
            # 1. Create new tables (test_suites, suite_runs, suite_test_cases)
            db.create_all()
            
            # 2. Add columns to existing tables if they don't exist
            print("Adding missing columns to existing tables...")
            from sqlalchemy import inspect
            bind = db.engine
            inspector = inspect(bind)
            
            # Add 'name' to test_cases
            test_cases_cols = [c['name'] for c in inspector.get_columns('test_cases')]
            if 'name' not in test_cases_cols:
                if bind.dialect.name == 'sqlite':
                    db.session.execute(text("ALTER TABLE test_cases ADD COLUMN name VARCHAR(255)"))
                else:
                    db.session.execute(text("ALTER TABLE test_cases ADD COLUMN IF NOT EXISTS name VARCHAR(255)"))
            
            # Add 'suite_run_id' to test_runs
            test_runs_cols = [c['name'] for c in inspector.get_columns('test_runs')]
            if 'suite_run_id' not in test_runs_cols:
                if bind.dialect.name == 'sqlite':
                    db.session.execute(text("ALTER TABLE test_runs ADD COLUMN suite_run_id VARCHAR(36) REFERENCES suite_runs(id)"))
                else:
                    db.session.execute(text("ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS suite_run_id UUID REFERENCES suite_runs(id)"))
            
            db.session.commit()
            print("Successfully updated database schema and columns.")
        except Exception as e:
            db.session.rollback()
            print(f"Error updating database: {e}")


if __name__ == "__main__":
    update_database()
