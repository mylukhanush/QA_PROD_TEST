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
        page.goto(os.getenv("JHS82_URL") + "/#/pages/reports-new/alert")
        page.wait_for_selector('ng-select', timeout=20000)
        
        # dump dropdowns
        print("Dumping multiselects:")
        els = page.locator('.multiselect-dropdown').all()
        for i, el in enumerate(els):
            try:
                print(f"[{i}] HTML: {el.evaluate('el => el.outerHTML').strip()[:500]}")
            except:
                pass
                
if __name__ == "__main__":
    run()
