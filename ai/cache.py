"""
Gemini context caching for site-map.json.

Since the site-map is sent with every generation request and rarely changes,
we cache its string representation and use Gemini's context caching
to reduce token costs across multiple calls.
"""
import json
import os
import datetime
import hashlib
from typing import Optional

# In-memory cache for sitemap string representation
_cached_content: Optional[str] = None
_cached_hash: Optional[str] = None

METADATA_FILE = ".gemini_cache_metadata.json"

def get_cached_site_map_content(site_map: dict) -> str:
    """
    Return the site-map as a JSON string, caching for reuse.
    If the site-map hasn't changed (by hash), return the cached version.
    """
    global _cached_content, _cached_hash

    current_json = json.dumps(site_map, indent=2, default=str)
    current_hash = hashlib.sha256(current_json.encode()).hexdigest()

    if _cached_hash == current_hash and _cached_content is not None:
        return _cached_content

    _cached_content = current_json
    _cached_hash = current_hash

    return _cached_content


def invalidate_cache():
    """Clear the cached site-map content (e.g., after a new crawl)."""
    global _cached_content, _cached_hash
    _cached_content = None
    _cached_hash = None
    if os.path.exists(METADATA_FILE):
        try:
            os.remove(METADATA_FILE)
        except Exception:
            pass


def setup_gemini_context_cache(site_map_json: str):
    """
    Ensures that site_map_json is cached in Gemini's server-side memory.
    Reuses existing active cache if it matches the current sitemap hash.
    Otherwise, uploads a new one and updates the local metadata file.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[GEMINI CACHE] GEMINI_API_KEY not found. Skipping server-side caching.")
        return None

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[GEMINI CACHE] Failed to initialize google-genai Client: {e}")
        return None

    current_hash = hashlib.sha256(site_map_json.encode("utf-8")).hexdigest()
    
    # 1. Try to read local metadata to find if we have an existing cache reference
    metadata = {}
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, "r") as f:
                metadata = json.load(f)
        except Exception:
            pass

    cached_name = metadata.get("cache_name")
    cached_hash = metadata.get("sitemap_hash")
    
    # 2. If we have a cached name, verify it with Gemini
    if cached_name and cached_hash == current_hash:
        try:
            cache = client.caches.get(name=cached_name)
            print(f"[GEMINI CACHE] Reusing existing valid Gemini Cache: {cache.name}")
            return cache
        except Exception as e:
            print(f"[GEMINI CACHE] Local metadata pointed to {cached_name}, but it is expired or invalid: {e}")
            # Recreate below

    # 3. If hash mismatch or expired, look through existing caches on Gemini to delete the old displays
    print("[GEMINI CACHE] Checking Gemini servers for display_name='qa-agent-site-map'...")
    try:
        for c in client.caches.list():
            if c.display_name == 'qa-agent-site-map':
                try:
                    client.caches.delete(name=c.name)
                    print(f"[GEMINI CACHE] Deleted old/stale cache: {c.name}")
                except Exception:
                    pass
    except Exception as e:
        print(f"[GEMINI CACHE] Failed to query/list caches on Gemini servers: {e}")
        if "denied access" in str(e).lower() or "403" in str(e):
            print("[GEMINI CACHE] Server-side caching is disabled due to API permissions.")
            return None

    # 4. Create a new cache on Gemini
    print("[GEMINI CACHE] Uploading site-map to Gemini Context Cache...")
    try:
        new_cache = client.caches.create(
            model='gemini-2.5-flash',
            config=types.CreateCachedContentConfig(
                display_name='qa-agent-site-map',
                contents=[f"SITE MAP (contains all available selectors and page structure):\n{site_map_json}\n"],
                ttl="86400s", # Expire in 24 hours (86400s)
            )
        )
        print(f"[GEMINI CACHE] Gemini Context Cache successfully created: {new_cache.name}")
        
        # Save metadata locally
        with open(METADATA_FILE, "w") as f:
            json.dump({
                "cache_name": new_cache.name,
                "sitemap_hash": current_hash,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }, f)
            
        return new_cache
    except Exception as e:
        print(f"[GEMINI CACHE] Failed to create Gemini Cache: {e}. Falling back to inline prompting.")
        return None
