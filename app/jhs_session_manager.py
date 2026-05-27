import uuid
import threading
import os
from playwright.sync_api import sync_playwright

def click_recaptcha_if_present(page, prefix="[JHS LOOP]", timeout_ms=3000):
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

class JHSSession:
    def __init__(self, username, password):
        self.id = str(uuid.uuid4())
        self.username = username
        self.password = password
        
        # Concurrency Events
        self.otp_ready_event = threading.Event()
        self.otp_input_event = threading.Event()
        self.login_result_event = threading.Event()
        
        # Shared states
        self.otp_code = None
        self.success = False
        self.error = None
        self.thread = None
        self.is_alive = True

    def start(self):
        self.thread = threading.Thread(target=self._run_browser_loop, name=f"JHS-Auth-{self.id}", daemon=True)
        self.thread.start()

    def _run_browser_loop(self):
        urls_to_try = [
            "https://jiohumsafar.jio.com/"
        ]
        
        cleaned_urls = []
        for u in urls_to_try:
            if u:
                u = u.strip()
                if not u.endswith("/"):
                    u += "/"
                cleaned_urls.append(u + "#/auth/login")
        
        if not cleaned_urls:
            cleaned_urls = ["https://jiohumsafar.jio.com/#/auth/login"]
            
        print(f"[JHS LOOP] Started background thread for {self.username}", flush=True)
        
        pw = None
        browser = None
        context = None
        page = None
        
        try:
            pw = sync_playwright().start()
            headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
            browser = pw.chromium.launch(headless=headless_env)
            context = browser.new_context(viewport={"width": 1280, "height": 720})
            page = context.new_page()
            
            otp_sent_successfully = False
            last_error = None
            
            for url in cleaned_urls:
                try:
                    print(f"[JHS LOOP] Navigating to: {url}", flush=True)
                    page.goto(url, wait_until="domcontentloaded", timeout=12000)
                    
                    # If we are on the landing page where the credentials form is hidden,
                    # click the top-right 'Login' button to display the form.
                    try:
                        landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
                        if landing_login_btn.is_visible():
                            print("[JHS LOOP] Landing page detected. Clicking 'Login' button to reveal form...", flush=True)
                            landing_login_btn.click()
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass
                        
                    # Wait for login input field
                    page.locator("input.form-control, input[formcontrolname='username']").first.wait_for(state="visible", timeout=4000)
                    
                    # Fill username
                    page.locator("input.form-control, input[formcontrolname='username']").first.fill(self.username)
                    
                    # Fill password
                    page.locator("input#password-field, input[type='password']").first.fill(self.password)
                    
                    # Click reCAPTCHA if present, then click JHS Login button
                    click_recaptcha_if_present(page, "[JHS LOGIN]", timeout_ms=1000)
                    page.locator("button.login_btn").first.click()
                    
                    # Wait for OTP field to appear
                    otp_sel = "input#otp_Email:visible, input[id*='otp']:visible, input[name='otp']:visible"
                    page.locator(otp_sel).first.wait_for(state="visible", timeout=6000)
                    
                    otp_sent_successfully = True
                    break
                except Exception as e:
                    print(f"[JHS LOOP] Failed on URL {url}: {e}", flush=True)
                    last_error = str(e)
                    # Check for explicit wrong credentials message
                    try:
                        body_text = page.locator("body").text_content() or ""
                        if any(w in body_text.lower() for w in ["invalid", "incorrect", "wrong", "password", "username", "exist"]):
                            last_error = "Incorrect JHS username or password."
                    except Exception:
                        pass
                    continue
            
            if not otp_sent_successfully:
                if last_error == "Incorrect JHS username or password.":
                    self.error = "Incorrect JHS username or password."
                else:
                    self.error = f"Could not connect to JHS. Details: {last_error or 'Network timeout'}"
                self.otp_ready_event.set()
                return
            
            # OTP dispatch is ready on JHS! Signal the Flask thread.
            print("[JHS LOOP] OTP dispatch completed. Signalling Flask.", flush=True)
            self.otp_ready_event.set()
            
            # Wait for user input of OTP code
            print("[JHS LOOP] Entering OTP verification loop...", flush=True)
            while self.is_alive:
                self.login_result_event.clear()
                user_clicked = self.otp_input_event.wait(timeout=180.0)
                
                if not user_clicked or not self.is_alive:
                    print("[JHS LOOP] OTP wait timed out or session terminated.", flush=True)
                    self.error = "OTP verification session timed out."
                    self.login_result_event.set()
                    break
                
                # Reset event flag
                self.otp_input_event.clear()
                
                print(f"[JHS LOOP] Received OTP code: '{self.otp_code}'. Refilling OTP field...", flush=True)
                otp_sel = "input#otp_Email:visible, input[id*='otp']:visible, input[name='otp']:visible"
                
                # Refill the input field safely
                try:
                    # Focus and instantly fill the visible OTP field
                    page.locator(otp_sel).first.fill(self.otp_code)
                    
                    # Check and handle Google reCAPTCHA during OTP submission
                    click_recaptcha_if_present(page, "[JHS OTP]", timeout_ms=5000)
                    
                    # Final click strictly on the JHS Login button
                    page.locator("button.login_btn").first.click()
                except Exception as form_err:
                    print(f"[JHS LOOP] Form fill error: {form_err}", flush=True)
                    self.error = "Browser session error. Please restart login."
                    self.login_result_event.set()
                    break
                
                 # Robust check for successful login or errors (up to 20 seconds)
                try:
                    success = False
                    for _ in range(40):  # 40 * 500ms = 20s
                        curr_url = page.url.lower()
                        # If URL has successfully redirected out of login/otp page into dashboard/home
                        if "dashboard" in curr_url or "pages" in curr_url or "home" in curr_url or ("login" not in curr_url and "otp" not in curr_url):
                            print(f"[JHS LOOP] Successful login redirect detected: {curr_url}", flush=True)
                            success = True
                            break
                        
                        # If sidebar or dashboard headers appear
                        try:
                            if page.locator(".sidebar-link, a[href*='dashboard'], .main-header, a[href*='reports']").count() > 0:
                                print("[JHS LOOP] Successful page selector detected!", flush=True)
                                success = True
                                break
                        except Exception:
                            pass
                            
                        # Look for visible OTP/credentials error texts on JHS page
                        try:
                            err_locs = page.locator(".alert-danger, .error-message, .alert-warning, [id*='error'], [class*='error']")
                            found_err = False
                            for i in range(err_locs.count()):
                                el = err_locs.nth(i)
                                if el.is_visible():
                                    txt = el.text_content() or ""
                                    if any(w in txt.lower() for w in ["invalid", "incorrect", "wrong", "otp", "code", "expired"]):
                                        self.error = f"Incorrect JHS OTP: {txt.strip()}"
                                        found_err = True
                                        break
                            if found_err:
                                break
                        except Exception:
                            pass
                            
                        page.wait_for_timeout(500)
                    
                    if success:
                        print("[JHS LOOP] Successfully authenticated! Waiting for storage settle...", flush=True)
                        page.wait_for_timeout(4000)
                        
                        # Save JHS authenticated storage state!
                        os.makedirs("captures", exist_ok=True)
                        context.storage_state(path="captures/jhs_state.json")
                        print("[JHS LOOP] JHS storage state saved to captures/jhs_state.json", flush=True)
                        
                        # Save sessionStorage manually
                        try:
                            import json
                            ss_data = page.evaluate("() => JSON.stringify(window.sessionStorage)")
                            ss_dict = json.loads(ss_data)
                            with open("captures/jhs_state_session_storage.json", "w", encoding="utf-8") as f:
                                json.dump(ss_dict, f)
                            print("[JHS LOOP] JHS sessionStorage saved to captures/jhs_state_session_storage.json", flush=True)
                        except Exception as e:
                            print(f"[JHS LOOP] Failed to save sessionStorage: {e}", flush=True)
                        
                        # Prime all environment-scoped states as well
                        import shutil
                        for env in ["jhs81", "jhs82", "jhs83", "jhs84"]:
                            try:
                                context.storage_state(path=f"captures/jhs_state_{env}.json")
                                # Copy session storage file too
                                shutil.copy("captures/jhs_state_session_storage.json", f"captures/jhs_state_{env}_session_storage.json")
                                print(f"[JHS LOOP] Primed shared session and sessionStorage for '{env}'", flush=True)
                            except Exception:
                                pass
                        
                        self.success = True
                        self.login_result_event.set()
                        break
                    else:
                        if not self.error:
                            self.error = "Incorrect JHS OTP code. Please enter the correct code."
                        print(f"[JHS LOOP] Verification failed: {self.error}", flush=True)
                        self.login_result_event.set()
                except Exception as inner_err:
                    self.error = f"Verification error: {inner_err}"
                    self.login_result_event.set()

        except Exception as e:
            print(f"[JHS LOOP] General Playwright execution loop error: {e}", flush=True)
            self.error = f"Verification failed: {e}"
            self.otp_ready_event.set()
            self.login_result_event.set()
        finally:
            print("[JHS LOOP] Cleaning up background browser context.", flush=True)
            self.is_alive = False
            try:
                if page: page.close()
            except Exception: pass
            try:
                if context: context.close()
            except Exception: pass
            try:
                if browser: browser.close()
            except Exception: pass
            try:
                if pw: pw.stop()
            except Exception: pass

    def close(self):
        print(f"[JHS MANAGER] Terminating background login session {self.id}.", flush=True)
        self.is_alive = False
        self.otp_input_event.set()  # Unlock loop if waiting
        
jhs_active_sessions = {}
