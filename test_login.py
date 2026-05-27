import sys
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

def click_recaptcha_if_present(page, prefix="[JHS LOGIN]"):
    recaptcha_iframe_sel = "iframe[src*='api2/anchor'], iframe[src*='enterprise/anchor'], iframe[title*='reCAPTCHA'], iframe[title*='robot'], iframe[src*='recaptcha']"
    try:
        # Wait up to 1.5 seconds for the iframe to be attached
        try:
            page.locator(recaptcha_iframe_sel).first.wait_for(state="attached", timeout=1500)
        except Exception:
            pass
        
        # Check if the iframe is present
        if page.locator(recaptcha_iframe_sel).count() > 0:
            iframe_element = page.locator(recaptcha_iframe_sel).first
            if iframe_element.is_visible():
                print(f"{prefix} reCAPTCHA detected! Locating checkbox...", flush=True)
                frame = page.frame_locator(recaptcha_iframe_sel).first
                
                # Locate checkbox inside iframe
                checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox, .recaptcha-checkbox-border").first
                
                # Wait for the checkbox to be visible inside the iframe (up to 10s)
                checkbox.wait_for(state="visible", timeout=10000)
                
                # Only click if not already checked
                checked = checkbox.get_attribute("aria-checked")
                if checked != "true":
                    print(f"{prefix} reCAPTCHA checkbox visible. Clicking it...", flush=True)
                    checkbox.click()
                    print(f"{prefix} reCAPTCHA checkbox clicked. Waiting for checkmark...", flush=True)
                    
                    # Wait up to 45 seconds for the tick mark (aria-checked="true")
                    for i in range(45):
                        checked = checkbox.get_attribute("aria-checked")
                        if checked == "true":
                            print(f"{prefix} reCAPTCHA successfully checked (tick mark visible)!", flush=True)
                            page.wait_for_timeout(1000)  # Tiny pause for state update
                            break
                        page.wait_for_timeout(1000)
                else:
                    print(f"{prefix} reCAPTCHA already checked (tick mark present).", flush=True)
    except Exception as e:
        print(f"{prefix} Error handling reCAPTCHA: {e}", flush=True)

def test_login():
    with sync_playwright() as p:
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
        browser = p.chromium.launch(headless=headless_env)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        print("Navigating to login page...")
        page.goto("https://jiohumsafar.jio.com/#/auth/login")
        
        # Click splash screen 'Login' button if visible
        try:
            landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
            if landing_login_btn.is_visible():
                print("Landing page detected. Clicking 'Login' button...")
                landing_login_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass
 
        print("Waiting for username field...")
        page.locator("input.form-control, input[formcontrolname='username']").first.wait_for(state="visible", timeout=15000)
        
        username = "110jiobpro@gmail.com"
        password = "JHSAdmin@123"
 
        print("Typing username...")
        page.locator("input.form-control, input[formcontrolname='username']").first.fill(username)
        
        print("Typing password...")
        page.locator("input#password-field, input[type='password']").first.fill(password)
        
        # Check and handle Google reCAPTCHA
        click_recaptcha_if_present(page, "[TEST LOGIN]")
            
        print("Clicking Send OTP...")
        page.locator("button.login_btn").first.click()
        
        print("Waiting for OTP field or error...")
        try:
            page.locator("input#otp_Email").wait_for(state="visible", timeout=5000)
            print("OTP field became visible!")
        except Exception as e:
            print("OTP field did NOT become visible:", str(e))
            
            # Check for any visible text that might indicate an error
            print("Page text snippet:")
            body_text = page.locator("body").text_content()
            print(body_text[:500])
            
        page.screenshot(path="login_debug.png", full_page=True)
        print("Screenshot saved to login_debug.png")
        browser.close()

if __name__ == "__main__":
    test_login()
