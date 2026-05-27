import sys
import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Navigating to login...")
        page.goto("http://jhs82.assettl.com/#/auth/login")
        page.fill("input.form-control", "ntpc.fbd")
        page.fill("input#password-field", "ntpc@123")
        page.click("button.login_btn")
        page.fill("input#otp_Email", "123456")
        page.click("button.login_btn")
        
        print("Waiting for dashboard...")
        page.wait_for_selector(".sidebar-link, a[href*='dashboard']", timeout=15000)
        
        print("Navigating to Alerts report...")
        page.goto("http://jhs82.assettl.com/#/pages/reports-new/alerts_summary")
        
        print("Waiting for page load...")
        time.sleep(5)
        
        print("Clicking View button...")
        page.click("button[title='View']")
        
        print("Waiting for 'No records found'...")
        time.sleep(3)
        
        html = page.content()
        with open("alert_report_empty.html", "w", encoding="utf-8") as f:
            f.write(html)
            
        print("Saved HTML.")
        browser.close()

if __name__ == "__main__":
    run()
