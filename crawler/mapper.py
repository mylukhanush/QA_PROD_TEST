"""
Site-map mapper — utilities for reading and querying site-map.json.
"""
import json
import os
from typing import Optional


_site_map_cache = {}
_site_map_mtime = 0.0

def load_site_map(path: Optional[str] = None) -> dict:
    """Load site-map.json from disk, with in-memory caching."""
    global _site_map_cache, _site_map_mtime
    
    path = path or os.getenv("SITE_MAP_PATH", "site-map.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"site-map.json not found at {path}. Run the crawler first."
        )
        
    current_mtime = os.stat(path).st_mtime
    if _site_map_cache and _site_map_mtime == current_mtime:
        return _site_map_cache

    with open(path, "r", encoding="utf-8") as f:
        _site_map_cache = json.load(f)
        _site_map_mtime = current_mtime
        return _site_map_cache


def get_login_info(site_map: dict) -> dict:
    """Return the login section from the site map."""
    return site_map.get("login", {})


def get_page_elements(site_map: dict, page_name: str) -> list:
    """Return all elements for a given page."""
    page_data = site_map.get("pages", {}).get(page_name, {})
    return page_data.get("elements", [])


def get_element_by_label(site_map: dict, label: str) -> Optional[dict]:
    """Find an element by its label across all pages."""
    for page_name, page_data in site_map.get("pages", {}).items():
        for el in page_data.get("elements", []):
            if el.get("label", "").lower() == label.lower():
                return {**el, "page": page_name}
    return None


def get_api_endpoints(site_map: dict, page_name: str) -> list:
    """Return API endpoint patterns for a page."""
    page_data = site_map.get("pages", {}).get(page_name, {})
    return page_data.get("api_endpoints", [])


def get_loading_indicators(site_map: dict, page_name: str) -> list:
    """Return loading indicator selectors for a page."""
    page_data = site_map.get("pages", {}).get(page_name, {})
    return page_data.get("loading_indicators", [])


def get_all_labels(site_map: dict) -> list:
    """Return a flat list of all element labels."""
    labels = []
    for page_name, page_data in site_map.get("pages", {}).items():
        for el in page_data.get("elements", []):
            labels.append(el.get("label", ""))
    return labels
