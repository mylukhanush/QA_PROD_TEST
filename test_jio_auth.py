import time
from playwright.sync_api import sync_playwright
from jio_auth.auth_handler import get_authenticated_context
from jio_auth.config import JIO_HUMSAFAR_PROD_URL

def test_jio_humsafar_automation():
    # Prompt user for the email ID they wish to authenticate
    target_email = input("\n[JHS TEST] Enter target email ID to authenticate (e.g. ranjit@assettl.com): ").strip()
    if not target_email:
        print("[JHS TEST] No email entered. Aborting test.")
        return
        
    print(f"\n[JHS TEST] Initiating headful test context for {target_email} on {JIO_HUMSAFAR_PROD_URL}...")
    
    with sync_playwright() as p:
        # Launch Chromium. headless=False makes debugging and entering OTP visually seamless!
        browser = p.chromium.launch(headless=False)
        
        try:
            # Retrieve pre-authenticated context
            context = get_authenticated_context(browser, target_email, JIO_HUMSAFAR_PROD_URL)
            
            # Open a page inside the pre-authenticated context
            page = context.new_page()
            
            # Go directly to the protected dashboard
            dashboard_url = JIO_HUMSAFAR_PROD_URL.rstrip("/") + "/#/pages/dashboard/aggregate-dashboard"
            print(f"[JHS TEST] Navigating directly to protected dashboard: {dashboard_url}")
            page.goto(dashboard_url, wait_until="domcontentloaded")
            
            # Verify if dashboard elements render (proving we bypassed login entirely!)
            try:
                page.wait_for_selector(".sidebar-link, a[href*='dashboard'], .main-header", timeout=8000)
                print(f"\n[JHS TEST] SUCCESS! Bypassed login and reached JHS Dashboard instantly for {target_email}!")
            except Exception:
                print(f"\n[JHS TEST] FAILED: Dashboard elements not found. Current URL is: {page.url}")
                
            print("\n[JHS TEST] Keeping the browser window open for 15 seconds to inspect...")
            time.sleep(15)
            
        except Exception as e:
            print(f"\n[JHS TEST] Error: {e}")
        finally:
            browser.close()
            print("[JHS TEST] Browser context closed.")

if __name__ == "__main__":
    test_jio_humsafar_automation()
