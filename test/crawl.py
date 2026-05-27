import os
import sys
import json
import time
import re
from datetime import datetime, timezone

# Add parent directory to path so we can import from crawler
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.extractor import (
    _site_env,
    _perform_login,
    _wait_for_page_ready,
    _expand_sidebar_accordions,
    _discover_nav_links,
    _extract_elements
)
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

def _generalize_endpoint(url):
    """Replace UUIDs and numbers with wildcards for clean deduplication"""
    url = url.split('?')[0]
    url = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{id}', url)
    url = re.sub(r'/\d+', '/{id}', url)
    return url

def _is_info_api(method, url):
    """Determine if an API is an 'info API' (returns data, not a mutation)"""
    url_lower = url.lower()
    if method == "GET":
        return True
    if method == "POST" and any(x in url_lower for x in ["get", "list", "info", "dashboard", "status", "fetch", "search", "summary", "report", "data"]):
        return True
    return False

def crawl_apis(site_name="jhs83"):
    env = _site_env(site_name)
    
    site_map = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "crawled_from": site_name,
        "login": {},
        "pages": {}
    }

    with sync_playwright() as pw:
        headless = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        # Shared state for the currently visited page
        current_page_apis = set()

        def handle_response(response):
            try:
                if response.request.resource_type in ["fetch", "xhr"]:
                    url = response.url
                    if url.endswith(('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff2', '.ttf', '.ico')):
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

        print(f"Logging in to {site_name}...")
        login_info = {}
        try:
            _perform_login(page, env, login_info)
            site_map["login"] = login_info
        except Exception as e:
            print(f"Login failed: {e}")
            return

        print("Waiting for page ready...")
        _wait_for_page_ready(page)
        
        print("Expanding sidebar accordions to discover all links...")
        _expand_sidebar_accordions(page)
        
        print("Discovering nav links...")
        nav_links = _discover_nav_links(page)
        
        print(f"Found {len(nav_links)} links. Visiting them to capture elements and APIs...")
        
        visited_urls = set()
        
        # Manually add dashboard
        dashboard_url = page.url
        if dashboard_url not in visited_urls:
             nav_links["dashboard"] = {"url": dashboard_url, "nav_selector": ""}

        for pname, pinfo in nav_links.items():
            url = pinfo.get("url")
            if url and url.startswith("http") and url not in visited_urls:
                print(f"  -> Visiting: {pname} ({url})")
                visited_urls.add(url)
                current_page_apis.clear()
                
                try:
                    nav_sel = pinfo.get("nav_selector", "")
                    nav_ok = False
                    if nav_sel:
                        try:
                            nav_loc = page.locator(nav_sel).first
                            if nav_loc.is_visible(timeout=2000):
                                nav_loc.dispatch_event("click")
                                page.wait_for_timeout(800)
                                nav_ok = True
                        except Exception:
                            pass
                    
                    if not nav_ok:
                        page.goto(url, wait_until="domcontentloaded", timeout=15000)
                        
                    _wait_for_page_ready(page)
                    time.sleep(2) # Give APIs time to settle
                    
                    # Extract elements like the real crawler
                    discovered_selectors = set()
                    elements = _extract_elements(page, pname, elements=[], discovered_selectors=discovered_selectors)
                    
                    # Interactively click internal elements to trigger lazy-loaded APIs and reveal new elements
                    safe_click_types = {"metric_card", "badge", "tab"}
                    clicked_count = 0
                    
                    # Iterate over a static copy of the initial interactive elements
                    interactive_elements = [el for el in elements if el.get("element_type") in safe_click_types]
                    
                    for el in interactive_elements:
                        try:
                            loc = page.locator(el["selector"]).first
                            if loc.is_visible(timeout=500):
                                loc.dispatch_event("click")
                                time.sleep(1.0) # Wait for APIs and DOM update
                                clicked_count += 1
                                # Re-extract any newly revealed elements into the same list
                                _extract_elements(page, pname, elements=elements, discovered_selectors=discovered_selectors)
                        except Exception:
                            pass
                    
                    site_map["pages"][pname] = {
                        "url": url,
                        "nav_selector": pinfo.get("nav_selector", ""),
                        "loading_indicators": [],
                        "api_endpoints": sorted(list(current_page_apis)),
                        "elements": elements
                    }
                    
                    print(f"     [Extracted {len(elements)} elements and {len(current_page_apis)} info APIs (clicked {clicked_count} internal elements)]")
                except Exception as e:
                    print(f"     [Error visiting {pname}]: {e}")

        # Save results matching site-map.json structure
        out_path = os.path.join(os.path.dirname(__file__), "site-map-apis.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(site_map, f, indent=2, ensure_ascii=False)
        
        print(f"\n=== DONE ===")
        print(f"Saved exact site-map structure with info APIs to: {out_path}")

if __name__ == "__main__":
    crawl_apis("jhs83")
