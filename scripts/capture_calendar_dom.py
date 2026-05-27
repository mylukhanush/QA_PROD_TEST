"""Capture the exact DOM of the date picker calendar popup."""
import os
import time
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

def run():
    url = os.getenv("JHS82_URL")
    username = os.getenv("JHS82_USERNAME")
    password = os.getenv("JHS82_PASSWORD")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        # Login
        print("Logging in...")
        page.goto(f"{url}/#/auth/login")
        page.wait_for_selector("input.form-control", timeout=15000)
        page.fill("input.form-control", username)
        page.fill("input#password-field", password)
        page.click("button.login_btn")
        page.wait_for_selector("input#otp_Email", timeout=15000)
        page.fill("input#otp_Email", "123456")
        page.click("button.login_btn")
        page.wait_for_selector(".sidebar-link, a[href*='dashboard']", timeout=15000)
        print("Logged in!")

        # Navigate to Distance Report
        print("Navigating to Distance Report...")
        page.goto(f"{url}/#/pages/reports-new/distance-report")
        time.sleep(3)

        # Click the date input to open the popup
        print("Opening date picker...")
        page.click("input[name='dateRange']")
        time.sleep(1)

        # Capture the calendar popup HTML
        # Try different possible container selectors
        calendar_html = page.evaluate("""() => {
            // Try to find the daterangepicker container
            const containers = [
                document.querySelector('.md-drppicker'),
                document.querySelector('.daterangepicker'),
                document.querySelector('ngx-daterangepicker-material'),
                document.querySelector('[class*="daterange"]'),
                document.querySelector('[class*="calendar"]'),
            ];
            for (const c of containers) {
                if (c) return c.outerHTML;
            }
            // Fallback: return any open popup/overlay
            const overlay = document.querySelector('.cdk-overlay-container');
            if (overlay && overlay.innerHTML.trim()) return overlay.outerHTML;
            return 'NO CALENDAR FOUND';
        }""")

        with open("calendar_dom.html", "w", encoding="utf-8") as f:
            f.write(calendar_html)
        print(f"Saved calendar DOM ({len(calendar_html)} chars) to calendar_dom.html")

        # Also take a screenshot
        page.screenshot(path="calendar_screenshot.png", full_page=True)
        print("Saved screenshot to calendar_screenshot.png")

        browser.close()

if __name__ == "__main__":
    run()
