#!/usr/bin/env python3
"""Smoke test: attempt login to a target site using the crawler's login routine.
Usage: run with the same env vars used for the crawler (e.g. JHS82_URL, JHS82_USERNAME, JHS82_PASSWORD).
"""
import os
import traceback
from crawler.extractor import _perform_login, _site_env
from playwright.sync_api import sync_playwright

site = os.environ.get('SMOKE_SITE', 'jhs82')
site_env = _site_env(site)
login_info = {}

print('Running smoke login for', site.upper())
print('Using URL:', site_env.get('url'))

with sync_playwright() as pw:
    headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
    browser = pw.chromium.launch(headless=headless_env)
    page = browser.new_page()
    try:
        res = _perform_login(page, site_env, login_info)
        print('\n=== LOGIN RESULT ===')
        print(res)
    except Exception as e:
        print('\n=== LOGIN ERROR ===')
        traceback.print_exc()
    finally:
        try:
            browser.close()
        except Exception:
            pass
