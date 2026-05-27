import time
import os
from playwright.sync_api import Browser, Page
from jio_auth.config import get_account_credentials, JIO_HUMSAFAR_PROD_URL, SCREENSHOTS_DIR
from jio_auth.session_manager import save_browser_session

# Setup Logging
import logging
logger = logging.getLogger("JioHumsafarAuth.Login")

def capture_debug_screenshot(page: Page, step_name: str):
    """Saves a timestamped screenshot on error or key workflow steps."""
    try:
        path = os.path.join(SCREENSHOTS_DIR, f"{step_name}_{int(time.time())}.png")
        page.screenshot(path=path)
        logger.info(f"[DEBUG] Screenshot saved for step '{step_name}' at {path}")
    except Exception as e:
        logger.error(f"[DEBUG] Failed to save screenshot: {e}")

def perform_interactive_login(browser: Browser, email: str, base_url: str = JIO_HUMSAFAR_PROD_URL) -> bool:
    """
    Performs login including:
    - Navigating to base_url/login
    - Clicking 'Login' button if on splash landing page
    - Submitting username & password
    - Handling OTP via console prompt (for headless) or browser interaction (for headful)
    - Saving storage state upon success
    """
    credentials = get_account_credentials(email)
    username = credentials["username"]
    password = credentials["password"]
    
    logger.info(f"[LOGIN] Starting login flow for {username}...")
    
    # Launch new context for clean slate login
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    
    try:
        login_url = base_url.rstrip("/") + "/#/auth/login"
        logger.info(f"[LOGIN] Navigating to {login_url}...")
        page.goto(login_url, wait_until="domcontentloaded", timeout=15000)
        
        # 1. Handle splash landing page if present
        try:
            landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
            if landing_login_btn.is_visible():
                logger.info("[LOGIN] Landing splash page detected. Clicking 'Login' button...")
                landing_login_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass
            
        # 2. Wait for credentials inputs
        username_sel = "input.form-control, input[formcontrolname='username']"
        password_sel = "input#password-field, input[type='password']"
        submit_sel = "button.login_btn"
        
        page.locator(username_sel).first.wait_for(state="visible", timeout=8000)
        
        # Fill Form
        page.locator(username_sel).first.fill(username)
        page.locator(password_sel).first.fill(password)
        
        # Check and handle Google reCAPTCHA
        recaptcha_iframe_sel = "iframe[title='reCAPTCHA'], iframe[src*='recaptcha']"
        try:
            page.wait_for_timeout(1000)
            if page.locator(recaptcha_iframe_sel).count() > 0 and page.locator(recaptcha_iframe_sel).first.is_visible():
                logger.info("[LOGIN] reCAPTCHA detected! Attempting to click checkbox...")
                frame = page.frame_locator(recaptcha_iframe_sel)
                checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox").first
                if checkbox.is_visible():
                    checkbox.click()
                    logger.info("[LOGIN] reCAPTCHA checkbox clicked. Waiting for checkmark...")
                    
                    # Wait up to 45 seconds for checkmark (manual solve in headful browser)
                    for i in range(45):
                        checked = checkbox.get_attribute("aria-checked")
                        if checked == "true":
                            logger.info("[LOGIN] reCAPTCHA successfully checked!")
                            break
                        page.wait_for_timeout(1000)
        except Exception as captcha_err:
            logger.error(f"[LOGIN] Error checking/resolving reCAPTCHA: {captcha_err}")
            
        logger.info("[LOGIN] Submitting credentials...")
        page.locator(submit_sel).first.click()
        
        # 3. Check for OTP dispatch
        otp_sel = "input#otp_Email:visible, input[id*='otp']:visible, input[name='otp']:visible"
        try:
            page.locator(otp_sel).first.wait_for(state="visible", timeout=8000)
            logger.info("[OTP] OTP request detected. An OTP has been sent to your email!")
        except Exception:
            logger.warning("[LOGIN] OTP field did not appear. Checking if already logged in or captcha present.")
            capture_debug_screenshot(page, "credentials_submitted_no_otp")
            
        # 4. Handle OTP Entry Loop
        success = False
        start_wait = time.time()
        
        while time.time() - start_wait < 180.0:  # 3 minutes total timeout
            curr_url = page.url.lower()
            
            # Check if login redirected into dashboard or home successfully
            if "dashboard" in curr_url or "pages" in curr_url or "home" in curr_url or ("login" not in curr_url and "otp" not in curr_url):
                # Extra selector check to be 100% sure pages have rendered
                if page.locator(".sidebar-link, a[href*='dashboard'], .main-header").count() > 0:
                    logger.info(f"[LOGIN] Success: Redirected to {curr_url}")
                    success = True
                    break
                    
            # Check for visible OTP/credentials errors on the page
            try:
                err_locs = page.locator(".alert-danger, .error-message, .alert-warning, [id*='error']")
                for i in range(err_locs.count()):
                    el = err_locs.nth(i)
                    if el.is_visible():
                        txt = el.text_content().strip()
                        if any(w in txt.lower() for w in ["invalid", "incorrect", "wrong", "otp", "code", "expired"]):
                            logger.error(f"[OTP ERROR] Page Alert: {txt}")
            except Exception:
                pass
                
            # If browser is headful, user can just type OTP in browser.
            # If browser is headless, prompt in console for the OTP:
            if page.locator(otp_sel).first.is_visible():
                # Check if field is empty (user hasn't typed anything yet)
                current_val = page.locator(otp_sel).first.input_value()
                if not current_val:
                    # In headless mode (or as a fallback), prompt in terminal:
                    logger.warning("[OTP PROMPT] Headless or manual terminal prompt triggered.")
                    otp_code = input(f"\n[JioHumsafar OTP] Please enter the OTP sent to {username}: ").strip()
                    if otp_code:
                        logger.info(f"[OTP] Filling OTP '{otp_code}'...")
                        page.locator(otp_sel).first.fill(otp_code)
                        
                        # Check and handle Google reCAPTCHA during OTP submission
                        recaptcha_iframe_sel = "iframe[title='reCAPTCHA'], iframe[src*='recaptcha']"
                        try:
                            page.wait_for_timeout(1000)
                            if page.locator(recaptcha_iframe_sel).count() > 0 and page.locator(recaptcha_iframe_sel).first.is_visible():
                                logger.info("[OTP] reCAPTCHA detected during OTP submission! Attempting to click checkbox...")
                                frame = page.frame_locator(recaptcha_iframe_sel)
                                checkbox = frame.locator("#recaptcha-anchor, .recaptcha-checkbox").first
                                if checkbox.is_visible():
                                    checked = checkbox.get_attribute("aria-checked")
                                    if checked != "true":
                                        checkbox.click()
                                        logger.info("[OTP] reCAPTCHA checkbox clicked. Waiting for checkmark...")
                                        
                                        # Wait up to 45 seconds for checkmark (manual solve in headful browser)
                                        for i in range(45):
                                            checked = checkbox.get_attribute("aria-checked")
                                            if checked == "true":
                                                logger.info("[OTP] reCAPTCHA successfully checked!")
                                                break
                                            page.wait_for_timeout(1000)
                                    else:
                                        logger.info("[OTP] reCAPTCHA already checked.")
                        except Exception as captcha_err:
                            logger.error(f"[OTP] Error checking/resolving reCAPTCHA during OTP: {captcha_err}")
                            
                        page.locator(submit_sel).first.click()
                        page.wait_for_timeout(1000)
                        
            page.wait_for_timeout(1000)
            
        if success:
            logger.info("[LOGIN] Authentication successful. Waiting for session tokens to settle...")
            page.wait_for_timeout(4000)
            
            # Save the session variables
            save_browser_session(page, email)
            logger.info(f"[LOGIN] Session saved successfully for {username}!")
            return True
        else:
            logger.error("[LOGIN] Login flow failed or timed out.")
            capture_debug_screenshot(page, "login_failure")
            return False
            
    except Exception as e:
        logger.error(f"[LOGIN] General exception in login loop: {e}")
        capture_debug_screenshot(page, "login_exception")
        return False
        
    finally:
        try: page.close()
        except Exception: pass
        try: context.close()
        except Exception: pass
