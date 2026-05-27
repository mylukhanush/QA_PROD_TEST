"""End-to-end test: select vehicle AP29TR7890, date 01-04-2026 to 12-05-2026, click View."""
import os
import sys
import time
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from runner.executor import _select_calendar_date


def run():
    url = os.getenv("JHS82_URL")
    username = os.getenv("JHS82_USERNAME")
    password = os.getenv("JHS82_PASSWORD")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
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

        # -- 1. Select Vehicle --
        print("Selecting vehicle AP29TR7890...")
        dropdown = page.locator(".multiselect-dropdown:has-text('Vehicle')").first
        dropdown.locator(".dropdown-btn").click()
        time.sleep(1)

        search_input = dropdown.locator(".filter-textbox input").first
        if search_input.count() > 0:
            search_input.fill("AP29TR7890")
            time.sleep(2)  # Give Angular more time to filter

        # Check how many items are in the dropdown now
        items = dropdown.locator(".dropdown-list li.multiselect-item-checkbox")
        print(f"  Found {items.count()} items after search")
        for i in range(min(items.count(), 5)):
            print(f"    Item {i}: '{items.nth(i).text_content().strip()}'")

        option = items.filter(has_text="AP29TR7890").first
        if option.count() > 0:
            option.click()
            print("  [OK] Vehicle selected")
        else:
            print("  [FAIL] Vehicle NOT found! Trying direct text click...")
            # Try clicking any visible item
            first_item = items.first
            if first_item.count() > 0:
                print(f"  Clicking first item: '{first_item.text_content().strip()}'")
                first_item.click()

        # Close dropdown by clicking elsewhere
        page.locator("body").click(position={"x": 700, "y": 100})
        time.sleep(0.5)

        # -- 2. Select Date Range: 01-04-2026 to 12-05-2026 --
        print("Selecting date range 01-04-2026 to 12-05-2026...")
        date_input = page.locator("input[name='dateRange']").first
        date_input.click()
        time.sleep(0.5)

        print("  Selecting start date: April 1...")
        _select_calendar_date(page, "01-04-2026")

        print("  Selecting end date: May 12...")
        _select_calendar_date(page, "12-05-2026")

        # Click OK
        print("  Clicking OK...")
        ok_btn = page.locator(".md-drppicker .buttons button.btn").first
        if ok_btn.count() > 0 and ok_btn.is_visible():
            ok_btn.click()
            print("  [OK] OK clicked")
        else:
            print("  [FAIL] OK button not found!")

        time.sleep(1)

        # -- 3. Click View --
        print("Clicking View...")
        page.click("button[title='View']")
        time.sleep(5)

        # Capture result
        page.screenshot(path="final_result.png", full_page=True)
        print("Saved final_result.png")

        browser.close()


if __name__ == "__main__":
    run()
