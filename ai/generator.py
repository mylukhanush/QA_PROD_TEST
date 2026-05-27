"""
Gemini AI Test Generator.

Accepts a plain-English situation description and the site-map.json,
generates a structured test plan with exact selectors and steps.
Uses Gemini context caching for the site-map to save tokens.
"""
import json
import builtins
import importlib
import os
import re
from typing import List, Optional
import time
from app.logging_config import log_event

# Must be set before google.generativeai imports protobuf internals.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

import warnings
warnings.filterwarnings("ignore", message="(?s).*All support")

_original_import_module = importlib.import_module
_original_import = builtins.__import__


def _protobuf_safe_import_module(name, package=None):
    """Let protobuf fall back when Python 3.14 rejects its native extension."""
    try:
        return _original_import_module(name, package)
    except TypeError as exc:
        is_protobuf_native_probe = name in {
            "google._upb._message",
            "google.protobuf.pyext._message",
        }
        if is_protobuf_native_probe and "custom tp_new" in str(exc):
            raise ImportError(name) from exc
        raise


def _protobuf_safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Convert protobuf native-extension TypeErrors into normal import misses."""
    try:
        return _original_import(name, globals, locals, fromlist, level)
    except TypeError as exc:
        is_protobuf_native_probe = (
            name in {"google._upb", "google._upb._message", "google.protobuf.pyext"}
            or name.startswith("google._upb.")
            or name.startswith("google.protobuf.pyext.")
        )
        if is_protobuf_native_probe and "custom tp_new" in str(exc):
            raise ImportError(name) from exc
        raise


importlib.import_module = _protobuf_safe_import_module
builtins.__import__ = _protobuf_safe_import
from google import genai
from google.genai import types

from ai.prompt import build_prompt
from ai.cache import get_cached_site_map_content
from crawler.mapper import load_site_map

# ── Gemini Setup ──────────────────────────────────────────────────

import datetime

_gemini_cache = None

def _get_client_and_config():
    """Return a genai.Client and default GenerateContentConfig, utilizing Context Caching if cache exists."""
    global _gemini_cache
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set in environment")

    client = genai.Client(api_key=api_key)
    
    # Check if cache exists and is still valid
    if _gemini_cache:
        try:
            client.caches.get(name=_gemini_cache.name)
        except Exception:
            _gemini_cache = None

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.2,
        cached_content=_gemini_cache.name if _gemini_cache else None
    )

    return client, config


def _load_site_credentials(target_sites: List[str]) -> dict:
    """Load site URLs and credentials from environment variables."""
    creds = {}
    for site in ["jhs81", "jhs82", "jhs83", "jhs84"]:
        url = os.getenv(f"{site.upper()}_URL", "")
        username = os.getenv(f"{site.upper()}_USERNAME", "")
        password = os.getenv(f"{site.upper()}_PASSWORD", "")
        if url:
            creds[site] = {"url": url, "username": username, "password": password}
    # Only return creds for the target sites (keep all if not filtering)
    if target_sites:
        return {k: v for k, v in creds.items() if k in target_sites} or creds
    return creds


def _candidate_finish_reason(response) -> Optional[str]:
    """Return Gemini's finish reason when available without assuming text exists."""
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            return str(getattr(candidates[0], "finish_reason", "") or "")
    except Exception:
        pass
    return None


def _response_text(response) -> str:
    """Extract text from a Gemini response/chunk while tolerating empty parts."""
    try:
        text = response.text
        return text or ""
    except Exception:
        pass

    pieces = []
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                text = getattr(part, "text", None)
                if text:
                    pieces.append(text)
    except Exception:
        pass

    return "".join(pieces)


def _raise_empty_gemini_response(response):
    finish_reason = _candidate_finish_reason(response)
    detail = f" finish_reason={finish_reason}" if finish_reason else ""
    raise ValueError(
        "Gemini returned no text for this request."
        f"{detail}. Try simplifying the prompt or reducing site-map context."
    )


# ── Generator ─────────────────────────────────────────────────────

def generate_test_plan(
    situation: str,
    target_sites: List[str],
    recent_tests: Optional[List[dict]] = None,
) -> dict:
    """
    Generate a test plan from a situation description.

    Parameters
    ----------
    situation : str
        Plain English description of what to test.
    target_sites : list of str
        Site names to target (jhs81, jhs82, etc.)
    recent_tests : list of dict, optional
        Recent test cases for dedup reference.

    Returns
    -------
    dict — structured test plan with steps, selectors, assertions.
    """
    # Load site map
    site_map = load_site_map()
    site_map_json = get_cached_site_map_content(site_map)

    # Load credentials
    site_credentials = _load_site_credentials(target_sites)

    # Initialize client and config with context caching
    client, config = _get_client_and_config()

    # Build the full prompt (site_map_json is None here so it doesn't double-include)
    prompt = build_prompt(
        situation=situation,
        target_sites=target_sites,
        site_map_json=None if _gemini_cache else site_map_json,
        recent_tests=recent_tests or [],
        site_credentials=site_credentials,
    )

    # Call Gemini
    log_event(
        "gemini_generate_start",
        situation=situation,
        target_sites=target_sites,
        cached_model=bool(_gemini_cache),
    )
    gemini_start = time.time()
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=config
        )
        gemini_duration = int((time.time() - gemini_start) * 1000)
    except Exception as e:
        gemini_duration = int((time.time() - gemini_start) * 1000)
        log_event(
            "gemini_generate_error",
            situation=situation,
            duration_ms=gemini_duration,
            error_type=e.__class__.__name__,
            error_message=str(e),
        )
        raise

    # Parse the JSON response (already guaranteed JSON by response_mime_type)
    try:
        raw_text = _response_text(response)
        if not raw_text.strip():
            _raise_empty_gemini_response(response)
        raw_text = re.sub(r'^```json\s*', '', raw_text.strip(), flags=re.IGNORECASE)
        raw_text = re.sub(r'```\s*$', '', raw_text).strip()
        plan = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raw_text = _response_text(response)
        log_event(
            "gemini_parse_error",
            situation=situation,
            duration_ms=gemini_duration,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        raise ValueError(f"Gemini returned invalid JSON: {exc}\nRaw: {raw_text[:500]}")

    # Sometimes Gemini wraps the response in an outer object or array
    if isinstance(plan, list) and len(plan) > 0:
        plan = plan[0]

    if isinstance(plan, dict) and "testName" not in plan:
        if "plan" in plan and isinstance(plan["plan"], dict):
            plan = plan["plan"]
        elif "testPlan" in plan and isinstance(plan["testPlan"], dict):
            plan = plan["testPlan"]

    # Validate required fields
    required_fields = ["testName", "category", "intent", "steps"]
    for field in required_fields:
        if field not in plan or not isinstance(plan, dict):
            keys = list(plan.keys()) if isinstance(plan, dict) else type(plan)
            raise ValueError(f"Generated plan missing required field: {field}. Available keys/type: {keys}\nRaw response snippet: {str(plan)[:200]}")

    # Ensure targetSites is set
    if "targetSites" not in plan:
        plan["targetSites"] = target_sites

    log_event(
        "gemini_generate_success",
        situation=situation,
        duration_ms=gemini_duration,
        test_name=plan.get("testName") if isinstance(plan, dict) else None,
    )
    return plan


def generate_test_plan_stream(
    situation: str,
    target_sites: List[str],
    recent_tests: Optional[List[dict]] = None,
):
    """
    Stream a generated test plan.
    Yields {"chunk": "..."} while generating, then {"final": True, "plan": {...}} at the end.
    """
    site_map = load_site_map()
    site_map_json = get_cached_site_map_content(site_map)
    site_credentials = _load_site_credentials(target_sites)

    client, config = _get_client_and_config()

    prompt = build_prompt(
        situation=situation,
        target_sites=target_sites,
        site_map_json=None if _gemini_cache else site_map_json,
        recent_tests=recent_tests or [],
        site_credentials=site_credentials,
    )

    log_event(
        "gemini_stream_start",
        situation=situation,
        target_sites=target_sites,
        cached_model=bool(_gemini_cache),
    )
    gemini_start = time.time()
    try:
        response = client.models.generate_content_stream(
            model='gemini-2.5-flash',
            contents=prompt,
            config=config
        )
    except Exception as e:
        gemini_duration = int((time.time() - gemini_start) * 1000)
        log_event(
            "gemini_stream_error",
            situation=situation,
            duration_ms=gemini_duration,
            error_type=e.__class__.__name__,
            error_message=str(e),
        )
        raise
    full_text = ""
    chunk_count = 0
    try:
        for chunk in response:
            chunk_count += 1
            chunk_text = _response_text(chunk)
            if chunk_text:
                full_text += chunk_text
                yield {"chunk": chunk_text}
    except Exception as e:
        gemini_duration = int((time.time() - gemini_start) * 1000)
        log_event(
            "gemini_stream_chunk_error",
            situation=situation,
            duration_ms=gemini_duration,
            chunk_count=chunk_count,
            error_type=e.__class__.__name__,
            error_message=str(e),
        )
        raise

    raw_text = full_text.strip()
    if not raw_text:
        _raise_empty_gemini_response(response)
    raw_text = re.sub(r'^```json\s*', '', raw_text, flags=re.IGNORECASE)
    raw_text = re.sub(r'```\s*$', '', raw_text).strip()
    
    try:
        plan = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        gemini_duration = int((time.time() - gemini_start) * 1000)
        log_event(
            "gemini_stream_parse_error",
            situation=situation,
            duration_ms=gemini_duration,
            error_type=exc.__class__.__name__,
            error_message=str(exc),
        )
        raise ValueError(f"Gemini returned invalid JSON: {exc}\nRaw: {full_text[:500]}")

    if isinstance(plan, list) and len(plan) > 0:
        plan = plan[0]

    if isinstance(plan, dict) and "testName" not in plan:
        if "plan" in plan and isinstance(plan["plan"], dict):
            plan = plan["plan"]
        elif "testPlan" in plan and isinstance(plan["testPlan"], dict):
            plan = plan["testPlan"]

    required_fields = ["testName", "category", "intent", "steps"]
    for field in required_fields:
        if field not in plan or not isinstance(plan, dict):
            raise ValueError(f"Generated plan missing required field: {field}")

    if "targetSites" not in plan:
        plan["targetSites"] = target_sites

    gemini_duration = int((time.time() - gemini_start) * 1000)
    log_event(
        "gemini_stream_success",
        situation=situation,
        duration_ms=gemini_duration,
        chunk_count=chunk_count,
        test_name=plan.get("testName") if isinstance(plan, dict) else None,
    )
    yield {"final": True, "plan": plan}
