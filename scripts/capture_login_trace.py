#!/usr/bin/env python3
"""Re-run login and capture traces, cookies, screenshots, HTML and network logs.
Saves artifacts to `captures/<site>-<timestamp>/`.
"""
import os
import uuid
import json
import time
from datetime import datetime
from crawler.extractor import _perform_login, _site_env
from playwright.sync_api import sync_playwright

site = os.environ.get('SMOKE_SITE', 'jhs82')
site_env = _site_env(site)
run_id = str(uuid.uuid4())
base_dir = os.path.join('captures', f"{site}-{int(time.time())}")
os.makedirs(base_dir, exist_ok=True)

print('Capture dir:', base_dir)
print('Target site:', site_env.get('url'))

requests = []
responses = []
navigations = []

with sync_playwright() as pw:
    # Use visible browser to mirror real behavior (set headless=True if you prefer)
    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
    browser = pw.chromium.launch(headless=headless_env)
    context = browser.new_context(viewport={"width":1280, "height":800})

    # Start tracing (screenshots + snapshots)
    try:
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
    except Exception:
        # Older playwright versions may not support 'sources'
        try:
            context.tracing.start(screenshots=True, snapshots=True)
        except Exception:
            pass

    page = context.new_page()

    def on_request(req):
        try:
            requests.append({
                'url': req.url,
                'method': req.method,
                'headers': dict(req.headers),
            })
        except Exception:
            pass

    def on_response(resp):
        try:
            responses.append({
                'url': resp.url,
                'status': resp.status,
                'headers': dict(resp.headers),
            })
        except Exception:
            pass

    def on_navigate(frame):
        try:
            navigations.append(frame.url)
        except Exception:
            pass

    page.on('request', on_request)
    page.on('response', on_response)
    page.on('framenavigated', on_navigate)

    login_meta = {}
    fail_screenshot = None
    html_before = None
    html_after = None
    try:
        # Capture pre-login HTML
        try:
            page.goto(site_env.get('url'), wait_until='domcontentloaded')
            html_before = page.content()
            with open(os.path.join(base_dir, 'before_login.html'), 'w', encoding='utf-8') as f:
                f.write(html_before)
        except Exception:
            pass

        # Perform the canonical login flow from crawler
        print('Performing login...')
        _perform_login(page, site_env, login_meta)
        print('Login attempt returned metadata:', login_meta)

        # Wait up to 30s to observe stability or redirect back to login
        redirected_back = False
        start = time.time()
        while time.time() - start < 30:
            cur = page.url.lower()
            if 'login' in cur or 'auth' in cur:
                print('Detected login URL after login flow:', cur)
                redirected_back = True
                break
            time.sleep(0.5)

        # Capture post-login HTML and screenshot
        try:
            html_after = page.content()
            with open(os.path.join(base_dir, 'after_login.html'), 'w', encoding='utf-8') as f:
                f.write(html_after)
        except Exception:
            pass

        screenshot_path = os.path.join(base_dir, f'{run_id}_screenshot.png')
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            screenshot_path = None

        # Save cookies/storage state
        try:
            state_path = os.path.join(base_dir, 'storage_state.json')
            context.storage_state(path=state_path)
        except Exception:
            state_path = None

        # Stop tracing and save
        try:
            trace_path = os.path.join(base_dir, 'trace.zip')
            context.tracing.stop(path=trace_path)
        except Exception:
            trace_path = None

        # Save network logs
        try:
            with open(os.path.join(base_dir, 'requests.json'), 'w', encoding='utf-8') as f:
                json.dump(requests, f, indent=2)
            with open(os.path.join(base_dir, 'responses.json'), 'w', encoding='utf-8') as f:
                json.dump(responses, f, indent=2)
            with open(os.path.join(base_dir, 'navigations.json'), 'w', encoding='utf-8') as f:
                json.dump(navigations, f, indent=2)
        except Exception:
            pass

        # Save login meta
        try:
            with open(os.path.join(base_dir, 'login_meta.json'), 'w', encoding='utf-8') as f:
                json.dump(login_meta, f, indent=2)
        except Exception:
            pass

        print('\nCapture summary:')
        print('screenshot:', screenshot_path)
        print('storage_state:', state_path)
        print('trace:', trace_path)
        print('redirected_back_after_login:', redirected_back)

    except Exception as e:
        print('Error during capture:', e)
        try:
            err_path = os.path.join(base_dir, 'error.txt')
            with open(err_path, 'w', encoding='utf-8') as f:
                f.write(str(e))
        except Exception:
            pass
    finally:
        try:
            browser.close()
        except Exception:
            pass

print('Artifacts saved in', base_dir)
