import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

def click_recaptcha_if_present(page, prefix="[TEST LOGIN]", timeout_ms=3000):
    recaptcha_iframe_sel = "iframe[src*='api2/anchor'], iframe[src*='enterprise/anchor'], iframe[title*='reCAPTCHA'], iframe[title*='robot'], iframe[src*='recaptcha']"
    try:
        # Wait for the iframe to be visible
        iframe_element = page.locator(recaptcha_iframe_sel).first
        iframe_element.wait_for(state="visible", timeout=timeout_ms)
        
        print(f"{prefix} reCAPTCHA iframe visible! Accessing frame locator...", flush=True)
        frame = page.frame_locator(recaptcha_iframe_sel).first
        
        # Locate checkbox inside the frame
        checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox, .recaptcha-checkbox-border").first
        checkbox.wait_for(state="visible", timeout=5000)
        
        checked = checkbox.get_attribute("aria-checked")
        if checked != "true":
            print(f"{prefix} Clicking reCAPTCHA checkbox...", flush=True)
            checkbox.click()
            print(f"{prefix} Clicked. Waiting up to 90s for green checkmark (aria-checked='true')...", flush=True)
            
            # Poll for the checkmark
            for _ in range(90):
                checked = checkbox.get_attribute("aria-checked")
                if checked == "true":
                    print(f"{prefix} reCAPTCHA successfully verified (checkmark active)!", flush=True)
                    page.wait_for_timeout(1000)
                    break
                page.wait_for_timeout(1000)
        else:
            print(f"{prefix} reCAPTCHA is already verified.", flush=True)
            
    except Exception as e:
        print(f"{prefix} No active reCAPTCHA interaction needed or timed out: {e}", flush=True)

def run_full_login_test():
    with sync_playwright() as p:
        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
        print(f"Launching browser (headless={headless_env})...")
        browser = p.chromium.launch(headless=headless_env)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()
        
        print("Navigating to JioHumsafar login page...")
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
        otp_code = "123421"

        print("Typing username...")
        page.locator("input.form-control, input[formcontrolname='username']").first.fill(username)
        
        print("Typing password...")
        page.locator("input#password-field, input[type='password']").first.fill(password)
        
        print("Clicking Send OTP...")
        page.locator("button.login_btn").first.click()
        
        # Wait for OTP field to appear
        print("Waiting for OTP field to appear...")
        otp_sel = "input#otp_Email:visible, input[id*='otp']:visible, input[name='otp']:visible"
        page.locator(otp_sel).first.wait_for(state="visible", timeout=15000)
        
        print(f"OTP field found! Typing OTP: {otp_code}...")
        page.locator(otp_sel).first.fill(otp_code)
        
        # Check and handle Google reCAPTCHA during OTP submission
        print("Checking for reCAPTCHA checkbox during OTP stage...")
        click_recaptcha_if_present(page, "[TEST OTP]", timeout_ms=5000)
        
        # Take a screenshot to show verification
        screenshot_path = "recaptcha_full_test.png"
        page.screenshot(path=screenshot_path, full_page=True)
        print(f"Verification screenshot saved to: {screenshot_path}")
        
        print("Clicking final Login button...")
        page.locator("button.login_btn").first.click()
        page.wait_for_timeout(4000)
        
        post_login_screenshot = "post_login_result.png"
        page.screenshot(path=post_login_screenshot, full_page=True)
        print(f"Post-login screenshot saved to: {post_login_screenshot}")
        
        browser.close()

if __name__ == "__main__":
    run_full_login_test()
