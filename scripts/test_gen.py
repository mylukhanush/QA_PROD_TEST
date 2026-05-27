import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()

from ai.generator import generate_test_plan

try:
    plan = generate_test_plan(
        situation="check the distance for all vehicle dated from 1st may to 12th may in reports",
        target_sites=["jhs81", "jhs82", "jhs83", "jhs84"]
    )
    print("SUCCESS!")
    print(json.dumps(plan, indent=2))
except Exception as e:
    print(f"ERROR: {e}")
