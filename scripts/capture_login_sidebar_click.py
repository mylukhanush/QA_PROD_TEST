#!/usr/bin/env python3
"""Login, wait a bit, click a sidebar option, and capture artifacts.
Saves to `captures/<site>-<timestamp>-sidebar/`.
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
base_dir = os.path.join('captures', f"{site}-{int(time.time())}-sidebar")
os.makedirs(base_dir, exist_ok=True)

requests = []
responses = []
navigations = []

print('Capture dir:', base_dir)
print('Target site:', site_env.get('url'))

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width":1280, "height":800})

    # Start tracing
    try:
        context.tracing.start(screenshots=True, snapshots=True)
    except Exception:
        pass

    page = context.new_page()

    page.on('request', lambda r: requests.append({'url': r.url, 'method': r.method}))
    page.on('response', lambda r: responses.append({'url': r.url, 'status': r.status}))
    page.on('framenavigated', lambda f: navigations.append(f.url))

    login_meta = {}
    try:
        # before-login HTML
        try:
            page.goto(site_env.get('url'), wait_until='domcontentloaded')
            with open(os.path.join(base_dir, 'before_login.html'), 'w', encoding='utf-8') as f:
                f.write(page.content())
        except Exception:
            pass

        # perform login
        print('Performing login...')
        _perform_login(page, site_env, login_meta)
        print('Login metadata:', login_meta)

        # Wait briefly to let app stabilize
        wait_secs = 6
        print(f'Waiting {wait_secs}s for stability...')
        time.sleep(wait_secs)

        # Try to find a sidebar link (choose first meaningful one)
        candidates = [
            "nav a", ".sidebar a", ".nav-link", ".menu a", "[role='navigation'] a",
            ".sidebar-nav a", ".side-menu a", "[class*='sidenav'] a", "a[href*='dashboard']",
            "a[href*='report']", "a[href*='device']", "a[href*='fleet']"
        ]
        clicked = None
        clicked_info = {}
        for sel in candidates:
            try:
                loc = page.locator(sel)
                cnt = loc.count()
                for i in range(min(cnt, 40)):
                    item = loc.nth(i)
                    try:
                        if not item.is_visible():
                            continue
                        href = item.get_attribute('href') or ''
                        text = (item.text_content() or '').strip()
                        if not href or href == '#' or href.lower().startswith('javascript'):
                            continue
                        if 'login' in href.lower() or 'auth' in href.lower():
                            continue
                        # Click and break
                        print(f'Clicking sidebar selector {sel} (text="{text}", href="{href}")')
                        try:
                            item.click(timeout=5000)
                        except Exception:
                            try:
                                page.evaluate(f"() => document.querySelector(\"{sel}\").click()")
                            except Exception:
                                pass
                        clicked = sel
                        clicked_info = {'selector': sel, 'text': text, 'href': href}
                        break
                    except Exception:
                        continue
                if clicked:
                    break
            except Exception:
                continue

        # wait for navigation or activity
        time.sleep(3)

        # capture after-click HTML and screenshot
        try:
            with open(os.path.join(base_dir, 'after_click.html'), 'w', encoding='utf-8') as f:
                f.write(page.content())
        except Exception:
            pass

        screenshot_path = os.path.join(base_dir, f'{run_id}_after_click.png')
        try:
            page.screenshot(path=screenshot_path, full_page=True)
        except Exception:
            screenshot_path = None

        # save storage/cookies
        try:
            state_path = os.path.join(base_dir, 'storage_state.json')
            context.storage_state(path=state_path)
        except Exception:
            state_path = None

        # stop tracing
        try:
            trace_path = os.path.join(base_dir, 'trace.zip')
            context.tracing.stop(path=trace_path)
        except Exception:
            trace_path = None

        # save network logs
        try:
            with open(os.path.join(base_dir, 'requests.json'), 'w', encoding='utf-8') as f:
                json.dump(requests, f, indent=2)
            with open(os.path.join(base_dir, 'responses.json'), 'w', encoding='utf-8') as f:
                json.dump(responses, f, indent=2)
            with open(os.path.join(base_dir, 'navigations.json'), 'w', encoding='utf-8') as f:
                json.dump(navigations, f, indent=2)
        except Exception:
            pass

        # store click metadata
        try:
            with open(os.path.join(base_dir, 'clicked.json'), 'w', encoding='utf-8') as f:
                json.dump(clicked_info, f, indent=2)
        except Exception:
            pass

        # determine if redirected back to login after click
        redirected_back = 'login' in page.url.lower() or 'auth' in page.url.lower()

        print('\nCapture summary:')
        print('clicked:', clicked_info)
        print('screenshot:', screenshot_path)
        print('storage_state:', state_path)
        print('trace:', trace_path)
        print('redirected_back_after_click:', redirected_back)

    except Exception as e:
        print('Error during capture:', e)
    finally:
        try:
            browser.close()
        except Exception:
            pass

print('Artifacts saved in', base_dir)
