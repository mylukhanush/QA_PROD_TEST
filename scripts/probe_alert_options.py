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
        
        # wait for the button
        page.wait_for_selector('button[title="Choose Alerts"]', timeout=15000)
        page.click('button[title="Choose Alerts"]')
        
        # Wait a bit for the dropdown to animate
        page.wait_for_timeout(1000)
        
        # Dump the HTML of whatever appeared
        # Usually it's appended to body or right next to the button
        print("Dropdown opened. Dumping HTML of .alert-dropdown or similar...")
        # Since I don't know the class, I will just dump the inner text of body and search for High/Medium
        body_text = page.evaluate('document.body.innerText')
        if "High" in body_text:
            print("Found High in body!")
            # Find elements containing High
            els = page.locator('*:has-text("High")').all()
            if els:
                # print the outer HTML of the innermost one
                last_el = els[-1]
                print(last_el.evaluate('el => el.outerHTML'))
                
        # Also let's check ng-select options
        page.click('ng-select[placeholder="Select Template"]')
        page.wait_for_timeout(1000)
        print("Template options:")
        els = page.locator('.ng-option').all()
        for el in els:
            print("NG-OPTION:", el.inner_text().strip())
                
if __name__ == "__main__":
    run()
