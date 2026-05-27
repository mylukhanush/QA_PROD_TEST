import json

with open("site-map.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("Pages found in site-map:")
for key in data.get("pages", {}).keys():
    if "command" in key or "cc" in key or "summary" in key:
        print(f"Key: {key}")
        page_data = data["pages"][key]
        print(f"URL: {page_data.get('url')}")
        print("Elements:")
        for el in page_data.get("elements", []):
            print(f"  Label: {el.get('label')} -> Selector: {el.get('selector')}")
