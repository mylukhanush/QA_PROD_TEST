import psycopg2
import json
try:
    conn = psycopg2.connect('dbname=qa_automation user=postgres password=root host=localhost')
    c = conn.cursor()
    c.execute("SELECT test_plan FROM test_cases WHERE id = (SELECT test_case_id FROM test_runs WHERE id = '1bca20f0-5ed3-4a0f-989b-f158ae55f465')")
    res = c.fetchone()
    if res:
        print(json.dumps(res[0], indent=2))
    else:
        print('Not found')
except Exception as e:
    print(e)
