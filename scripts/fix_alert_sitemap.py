import json

with open('site-map.json', 'r', encoding='utf-8') as f:
    sm = json.load(f)

alert_elements = sm['pages']['reports_alert']['elements']

# Remove all old Alert Category entries
alert_elements[:] = [e for e in alert_elements if 'Alert Category' not in e.get('label', '')]

# Find insertion point: after the Vehicle select all checkbox
insert_idx = None
for i, e in enumerate(alert_elements):
    if 'Vehicle select all' in e.get('label', ''):
        insert_idx = i + 1
        break

if insert_idx is None:
    insert_idx = 4  # fallback

new_elements = [
    {
        "label": "Choose Alerts button (open alert type popup)",
        "selector": 'button[title="Choose Alerts"]',
        "backup_selector": "button.alert-col-btn",
        "element_type": "button",
        "section": "filters",
        "is_dynamic": False,
        "value_sample": "Accident +40",
        "text_anchor_label": "Choose Alerts"
    },
    {
        "label": "High alert category checkbox",
        "selector": ".high-alert label.filter_check_container",
        "backup_selector": "",
        "element_type": "checkbox",
        "section": "filters",
        "is_dynamic": False,
        "value_sample": "High (41)",
        "text_anchor_label": "High"
    },
    {
        "label": "Medium alert category checkbox",
        "selector": ".medium-alert label.filter_check_container",
        "backup_selector": "",
        "element_type": "checkbox",
        "section": "filters",
        "is_dynamic": False,
        "value_sample": "Medium",
        "text_anchor_label": "Medium"
    },
    {
        "label": "Low alert category checkbox",
        "selector": ".low-alert label.filter_check_container",
        "backup_selector": "",
        "element_type": "checkbox",
        "section": "filters",
        "is_dynamic": False,
        "value_sample": "Low",
        "text_anchor_label": "Low"
    },
    {
        "label": "Close alert type popup",
        "selector": '.Alert-dropdown .material-icons:has-text("close")',
        "backup_selector": "",
        "element_type": "button",
        "section": "filters",
        "is_dynamic": False,
        "value_sample": "close",
        "text_anchor_label": "Close"
    },
]

for j, elem in enumerate(new_elements):
    alert_elements.insert(insert_idx + j, elem)

with open('site-map.json', 'w', encoding='utf-8') as f:
    json.dump(sm, f, indent=2)

print("Updated site-map.json with exact Alert selectors:")
for e in new_elements:
    print(f"  {e['label']}: {e['selector']}")
