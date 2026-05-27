"""Run the BFS crawler for jhs82 and log progress to crawl.log."""
import datetime
from dotenv import load_dotenv
load_dotenv()

# Set standard dynamic fallbacks
os.environ.setdefault("DATABASE_URL", os.getenv("DATABASE_URL", "postgresql://postgres:root@localhost:5432/qa_automation"))
os.environ.setdefault("FLASK_SECRET_KEY", os.getenv("FLASK_SECRET_KEY", "qa-agent-secret-key-2026"))
os.environ.setdefault("JHS82_URL", "https://jiohumsafar.jio.com/")
os.environ.setdefault("JHS82_USERNAME", os.getenv("JHS82_USERNAME", "ranjit@assettl.com"))
os.environ.setdefault("JHS82_PASSWORD", os.getenv("JHS82_PASSWORD", "Rjil@12345"))

from app import create_app
app = create_app()

LOG = open("crawl.log", "w", encoding="utf-8", buffering=1)

def p(pct, msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"{ts} [{pct:3d}%] {msg}"
    print(line, flush=True)
    LOG.write(line + "\n")

with app.app_context():
    from crawler.extractor import crawl_site
    result = crawl_site("jhs82", progress_callback=p)

LOG.close()
print("\n=== DONE ===")
print(result)
