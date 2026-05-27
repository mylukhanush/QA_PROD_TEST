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
        
        # go to alerts report properly via clicks
        page.click('.nav-link:has-text("Reports")')
        page.wait_for_selector('div.widget-title:has-text("Alert")', timeout=10000)
        page.click('div.widget-title:has-text("Alert")')
        
        page.wait_for_selector('.multiselect-dropdown', timeout=15000)
        
        # dump dropdowns
        print("Dumping ALL dropdown-like elements in the top bar:")
        # The top bar is usually something like .form-group or .row
        top_bar = page.locator('.row').first
        print(top_bar.evaluate('el => el.innerHTML').strip())
                
if __name__ == "__main__":
    run()
