"""
QA Automation Tool — Application Entry Point.

Run with:
    python run.py          → starts Flask web server
    python run.py --help   → shows CLI commands
"""
import os
import warnings
# Suppress deprecation warnings from legacy google-generativeai package
warnings.filterwarnings("ignore", message="(?s).*All support")

from dotenv import load_dotenv

load_dotenv()

# Attempt to start PostgreSQL service automatically if database is PostgreSQL
if os.getenv("DATABASE_URL", "").startswith("postgresql"):
    try:
        import subprocess
        import platform
        import re
        if platform.system() == "Windows":
            result = subprocess.run(
                ["sc", "query", "state=", "all"],
                capture_output=True,
                text=True,
                check=False
            )
            services = re.findall(r"SERVICE_NAME:\s*(postgresql\S*)", result.stdout, re.IGNORECASE)
            for service in services:
                print(f"Attempting to automatically start PostgreSQL service: {service}...")
                subprocess.run(["net", "start", service], capture_output=True, check=False)
    except Exception:
        pass

# Avoid protobuf C-extension crashes on newer Python runtimes.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=os.getenv("FLASK_ENV", "development") == "development",
    )
