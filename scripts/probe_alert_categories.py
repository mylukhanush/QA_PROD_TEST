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
        
        # Now probe the popup structure for High/Medium/Low
        # Get the full HTML of the Alert-dropdown container
        html = page.locator('.Alert-dropdown').first.inner_html()
        
        # Save full HTML to file for analysis
        with open('alert_dropdown_full.html', 'w', encoding='utf-8') as f:
            f.write(html)
        
        # Try to find "High" text elements
        print("=== Looking for High/Medium/Low elements ===")
        
        # Check checkboxes that might be category headers
        all_checkboxes = page.locator('.Alert-dropdown input[type="checkbox"]').all()
        print(f"Total checkboxes in Alert dropdown: {len(all_checkboxes)}")
        
        # Look for text containing High, Medium, Low
        for text_to_find in ["High", "Medium", "Low"]:
            els = page.locator(f'.Alert-dropdown *:has-text("{text_to_find}")').all()
            print(f"\nElements matching '{text_to_find}': {len(els)}")
            # Get the most specific (innermost) one
            if els:
                for i, el in enumerate(els[-3:]):  # last 3 (most specific)
                    try:
                        tag = el.evaluate('el => el.tagName')
                        cls = el.evaluate('el => el.className')
                        txt = el.inner_text().strip()[:80]
                        outer = el.evaluate('el => el.outerHTML')[:300]
                        print(f"  [{i}] tag={tag} class={cls} text={txt}")
                        print(f"       html={outer}")
                    except:
                        pass
        
        # Also check if there's a specific structure like tabs or headers
        print("\n=== Direct children of the popup ===")
        children = page.locator('.Alert-dropdown > div').all()
        for i, ch in enumerate(children[:5]):
            try:
                txt = ch.inner_text().strip()[:100]
                cls = ch.evaluate('el => el.className')
                print(f"  child[{i}] class={cls} text={txt}")
            except:
                pass
                
        # Now try clicking High
        print("\n=== Trying to find clickable High element ===")
        # From the screenshot, "High (41)" has a checkbox - look for it
        high_label = page.locator('.Alert-dropdown label:has-text("High")')
        if high_label.count() > 0:
            print(f"Found label with 'High': count={high_label.count()}")
            print(f"  HTML: {high_label.first.evaluate('el => el.outerHTML')[:300]}")
        
        high_input = page.locator('.Alert-dropdown input[type="checkbox"]').first
        if high_input.count() > 0:
            print(f"First checkbox HTML: {high_input.evaluate('el => el.outerHTML')[:300]}")
            parent = high_input.evaluate('el => el.parentElement.outerHTML')[:300]
            print(f"  Parent HTML: {parent}")
                
if __name__ == "__main__":
    run()
