import sys
import time
from playwright.sync_api import sync_playwright

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("Navigating to login...")
        page.goto("https://jhs82.assettl.com/#/auth/login")
        
        try:
            page.wait_for_selector("input[name='username'], input.form-control", timeout=15000)
            page.fill("input[name='username'], input.form-control", "ntpc.fbd")
            page.fill("input[name='password'], input#password-field", "ntpc@123")
            page.click("button.login_btn")
            page.fill("input#otp_Email", "123456")
            page.click("button.login_btn")
        except Exception as e:
            print("Login failed:", e)
            html = page.content()
            with open("login_fail.html", "w", encoding="utf-8") as f:
                f.write(html)
            return
        
        print("Waiting for dashboard...")
        page.wait_for_selector(".sidebar-link, a[href*='dashboard']", timeout=15000)
        
        print("Navigating to Reports Distance...")
        page.goto("https://jhs82.assettl.com/#/pages/reports-new/distance-report")
        
        print("Waiting for page load...")
        time.sleep(5)
        
        print("Clicking input...")
        page.click("input[name='dateRange']")
        time.sleep(1)
        
        print("Evaluating JS on input[name='dateRange']")
        # In ngx-daterangepicker-material, we might need to find the specific days and click them
        # Let's see if we can extract the HTML of the calendar to understand its structure
        html = page.content()
        with open("date_picker.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved date_picker.html")
        
        browser.close()

if __name__ == "__main__":
    run()
