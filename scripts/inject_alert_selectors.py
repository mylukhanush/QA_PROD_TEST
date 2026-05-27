import json

with open('site-map.json', 'r', encoding='utf-8') as f:
    sm = json.load(f)

alert_page = sm['pages'].get('reports_alert')
if alert_page:
    elements = alert_page.setdefault('elements', [])
    
    # Check if 'Alert Category' is already there
    if not any('Alert Category' in e['label'] for e in elements):
        elements.insert(4, {
            'label': 'Alert Category dropdown button',
            'selector': '.multiselect-dropdown:not(:has-text("Vehicle")) .dropdown-btn',
            'backup_selector': '',
            'element_type': 'dropdown',
            'section': 'filters',
            'is_dynamic': False,
            'value_sample': 'Accident +68',
            'text_anchor_label': 'Alert Category'
        })
        elements.insert(5, {
            'label': 'Alert Category option High',
            'selector': '.multiselect-dropdown:not(:has-text("Vehicle")) li:has-text("High")',
            'backup_selector': '',
            'element_type': 'checkbox',
            'section': 'filters',
            'is_dynamic': False,
            'value_sample': 'High',
            'text_anchor_label': 'High'
        })
        elements.insert(6, {
            'label': 'Alert Category option Medium',
            'selector': '.multiselect-dropdown:not(:has-text("Vehicle")) li:has-text("Medium")',
            'backup_selector': '',
            'element_type': 'checkbox',
            'section': 'filters',
            'is_dynamic': False,
            'value_sample': 'Medium',
            'text_anchor_label': 'Medium'
        })
        elements.insert(7, {
            'label': 'Alert Category option Low',
            'selector': '.multiselect-dropdown:not(:has-text("Vehicle")) li:has-text("Low")',
            'backup_selector': '',
            'element_type': 'checkbox',
            'section': 'filters',
            'is_dynamic': False,
            'value_sample': 'Low',
            'text_anchor_label': 'Low'
        })
        
        with open('site-map.json', 'w', encoding='utf-8') as f:
            json.dump(sm, f, indent=2)
        print('Injected Alert Category selectors successfully.')
    else:
        print('Alert Category already exists.')
else:
    print('reports_alert not found.')
