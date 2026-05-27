import psycopg2, json

conn = psycopg2.connect('dbname=qa_automation user=postgres password=root host=localhost')
c = conn.cursor()
c.execute("SELECT test_plan FROM test_cases WHERE id = (SELECT test_case_id FROM test_runs WHERE id = '64e80c5f-4f51-4b34-becc-a3cfad170f12')")
res = c.fetchone()
if res:
    plan = res[0]
    for s in plan.get('steps', []):
        sid = s.get('id', '')
        desc = s.get('description', '')
        target = s.get('target', '')
        print(f"{sid}: {desc}")
        print(f"   target: {target}")
        print()
