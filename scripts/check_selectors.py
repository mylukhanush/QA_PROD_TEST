import json
with open('site-map.json', 'r', encoding='utf-8') as f:
    sm = json.load(f)
for e in sm['pages']['reports_alert']['elements']:
    lbl = e['label'].lower()
    if 'alert' in lbl or 'template' in lbl or 'category' in lbl or 'high' in lbl or 'medium' in lbl or 'low' in lbl:
        print(f"  {e['label']}: {e['selector']}")
