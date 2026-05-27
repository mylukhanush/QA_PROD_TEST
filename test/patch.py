import sys

with open("test/extractor_test.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add api helper functions
api_helpers = """
import re

def _generalize_endpoint(url):
    url = url.split('?')[0]
    url = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}', url)
    url = re.sub(r'/\d+', '/{id}', url)
    return url

def _is_info_api(method, url):
    url_lower = url.lower()
    if method == "GET":
        return True
    if method == "POST" and any(x in url_lower for x in ["get", "list", "info", "dashboard", "status", "fetch", "search", "summary", "report", "data"]):
        return True
    return False

"""

content = content.replace("import os\n", "import os\n" + api_helpers)

# 2. Add API interception to playwright
interception_code = """
        current_page_apis = set()
        
        def handle_response(response):
            try:
                if response.request.resource_type in ["fetch", "xhr"]:
                    url = response.url
                    if url.endswith(('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff2', '.ttf', '.ico', '.html')):
                        return
                    method = response.request.method
                    content_type = response.headers.get('content-type', '')
                    is_json = 'application/json' in content_type
                    if is_json or _is_info_api(method, url):
                        generalized_url = _generalize_endpoint(url)
                        endpoint_str = f"{method} {generalized_url}"
                        current_page_apis.add(endpoint_str)
            except Exception:
                pass

        page.on("response", handle_response)
"""

content = content.replace("page = context.new_page()", "page = context.new_page()\n" + interception_code)

# 3. Clear APIs at start of loop
content = content.replace("url, pname, nav_sel, depth = crawl_queue.popleft()", 
                          "url, pname, nav_sel, depth = crawl_queue.popleft()\n            current_page_apis.clear()")

# 4. Save APIs to site_map
# For the exception case
content = content.replace('"api_endpoints": [],', '"api_endpoints": sorted(list(current_page_apis)),')
# For the success case. Wait, in extractor.py it might be `_capture_api_endpoints([])` but I couldn't find it in grep_search? 
# I will just regex replace `"api_endpoints": [^,]+,` with `"api_endpoints": sorted(list(current_page_apis)),`
import re
content = re.sub(r'"api_endpoints": [^,]+,', '"api_endpoints": sorted(list(current_page_apis)),', content)

# 5. Disable DB integration
content = content.replace("SiteElement.query.delete()", "pass # SiteElement.query.delete()")
content = content.replace("db.session.add(SiteElement(", "pass # db.session.add(")
content = content.replace("db.session.commit()", "pass # db.session.commit()")

# 6. Change output path
content = content.replace('os.getenv("SITE_MAP_PATH", "site-map.json")', 'os.path.join(os.path.dirname(__file__), "site-map-apis.json")')

# 7. Disable _capture_api_endpoints missing reference just in case
content = content.replace("_capture_api_endpoints([])", "sorted(list(current_page_apis))")

with open("test/extractor_test.py", "w", encoding="utf-8") as f:
    f.write(content)

# create run block
run_block = """
if __name__ == "__main__":
    print("Starting deep crawl on jhs83...")
    def prog(pct, msg):
        print(f"[{pct}%] {msg}")
    crawl_site("jhs83", prog)
"""
with open("test/extractor_test.py", "a", encoding="utf-8") as f:
    f.write(run_block)

print("Patched!")
