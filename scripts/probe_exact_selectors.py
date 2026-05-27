import json
import time
from playwright.sync_api import sync_playwright
import os
from dotenv import load_dotenv

load_dotenv()

def run():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        
        # login
        page.goto(os.getenv("JHS82_URL"))
        page.wait_for_selector("input.form-control", timeout=10000)
        page.fill("input.form-control", os.getenv("JHS82_USERNAME"))
        page.fill("input#password-field", os.getenv("JHS82_PASSWORD"))
        page.click("button.login_btn")
        page.fill("input#otp_Email", "123456")
        page.click("button.login_btn")
        page.wait_for_selector(".nav-item", timeout=10000)
        
        # go to alerts report
        page.click('.nav-link:has-text("Reports")')
        page.wait_for_selector('div.widget-title:has-text("Alert")', timeout=10000)
        page.click('div.widget-title:has-text("Alert")')
        
        # open alert dropdown
        page.wait_for_selector('button[title="Choose Alerts"]', timeout=15000)
        page.click('button[title="Choose Alerts"]')
        page.wait_for_timeout(1500)
        
        # Test the exact selectors we want to use
        selectors_to_test = {
            "Open Alert popup": 'button[title="Choose Alerts"]',
            "High category": '.high-alert label.filter_check_container',
            "Medium category": '.medium-alert label.filter_check_container',
            "Low category (attempt 1)": '.Alert-dropdown .alert-filters > div:nth-child(3) label.filter_check_container',
            "Close popup": '.Alert-dropdown .close-icon',
        }
        
        for name, sel in selectors_to_test.items():
            count = page.locator(sel).count()
            print(f"  {name}: count={count}, selector={sel}")
            if count > 0:
                txt = page.locator(sel).first.inner_text().strip()[:50]
                print(f"    text: {txt}")
        
        # Find Low specifically
        print("\n=== Finding Low column ===")
        # The structure is .alert-filters > div.col-4 (3 of them: high-alert, medium-alert, ???)
        cols = page.locator('.alert-filters > div.col-4').all()
        print(f"Number of col-4 divs: {len(cols)}")
        for i, col in enumerate(cols):
            cls = col.evaluate('el => el.className')
            txt = col.inner_text().strip()[:50]
            print(f"  col[{i}] class={cls} text={txt}")
            
        # Find the close button
        print("\n=== Close button ===")
        close_candidates = [
            '.Alert-dropdown button:has-text("close")',
            '.Alert-dropdown .material-icons:has-text("close")',
            '.Alert-dropdown span:has-text("close")',
        ]
        for sel in close_candidates:
            count = page.locator(sel).count()
            if count > 0:
                print(f"  Found: {sel} (count={count})")
                html = page.locator(sel).first.evaluate('el => el.outerHTML')[:200]
                print(f"    HTML: {html}")

if __name__ == "__main__":
    run()
