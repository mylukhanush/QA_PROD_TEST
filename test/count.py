import json
d1 = json.load(open('site-map.json', encoding='utf-8'))
d2 = json.load(open('test/site-map-apis.json', encoding='utf-8'))
print(f"site-map.json: {len(d1.get('pages',{}))} pages")
print(f"test/site-map-apis.json: {len(d2.get('pages',{}))} pages")
