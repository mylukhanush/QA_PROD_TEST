import uuid
import threading
import os
from playwright.sync_api import sync_playwright

class JHSSession:
    def __init__(self, username, password):
        self.id = str(uuid.uuid4())
        self.username = username
        self.password = password
        
        # Concurrency Events (kept for compatibility)
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
        self.thread = threading.Thread(target=self._run_browser_loop, name=f"JioHumsafar-Auth-{self.id}", daemon=True)
        self.thread.start()

    def _run_browser_loop(self):
        url = "https://jiohumsafar.jio.com/#/auth/login"
        print(f"[Jio Humsafar Loop] Started background thread for {self.username}. Launching headful browser...", flush=True)
        
        pw = None
        browser = None
        context = None
        page = None
        
        try:
            pw = sync_playwright().start()
            # Force headless=False so the user can interact, solve captcha, and enter OTP manually!
            browser = pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = context.new_page()
            
            print(f"[Jio Humsafar Loop] Navigating to: {url}", flush=True)
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            
            # If we are on the landing page where the credentials form is hidden, click 'Login'
            try:
                landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
                if landing_login_btn.is_visible():
                    landing_login_btn.click()
                    page.wait_for_timeout(1000)
            except Exception:
                pass
                
            # Wait for login input field to be ready
            page.locator("input.form-control, input[formcontrolname='username']").first.wait_for(state="visible", timeout=8000)
            
            # Autofill username and password
            page.locator("input.form-control, input[formcontrolname='username']").first.fill(self.username)
            page.locator("input#password-field, input[type='password']").first.fill(self.password)
            print("[Jio Humsafar Loop] Autofilled credentials. Waiting for user to complete captcha and OTP manually...", flush=True)
            
            # Wait loop to check when the page successfully logs in and redirects
            success = False
            for _ in range(300): # Wait up to 5 minutes
                if not self.is_alive or page.is_closed():
                    break
                    
                curr_url = page.url.lower()
                # Check for redirect to dashboard or home page
                if "dashboard" in curr_url or "pages" in curr_url or "home" in curr_url or ("login" not in curr_url and "otp" not in curr_url):
                    print(f"[Jio Humsafar Loop] Successful login redirect detected: {curr_url}", flush=True)
                    success = True
                    break
                    
                # Alternate check: dashboard sidebar elements
                try:
                    if page.locator(".sidebar-link, a[href*='dashboard'], .main-header, a[href*='reports']").count() > 0:
                        print("[Jio Humsafar Loop] Successful dashboard page element detected!", flush=True)
                        success = True
                        break
                except Exception:
                    pass
                    
                page.wait_for_timeout(1000)
                
            if success:
                print("[Jio Humsafar Loop] Successfully authenticated! Saving storage state...", flush=True)
                page.wait_for_timeout(3000) # Wait for storage to settle
                
                os.makedirs("captures", exist_ok=True)
                context.storage_state(path="captures/jhs_state.json")
                
                # Save sessionStorage manually
                try:
                    import json
                    ss_data = page.evaluate("() => JSON.stringify(window.sessionStorage)")
                    ss_dict = json.loads(ss_data)
                    with open("captures/jhs_state_session_storage.json", "w", encoding="utf-8") as f:
                        json.dump(ss_dict, f)
                    print("[Jio Humsafar Loop] Saved sessionStorage.", flush=True)
                except Exception as ss_err:
                    print(f"[Jio Humsafar Loop] SessionStorage capture failed: {ss_err}", flush=True)
                    
                # Priming other env environments as well
                import shutil
                for env in ["jhs81", "jhs82", "jhs83", "jhs84"]:
                    try:
                        context.storage_state(path=f"captures/jhs_state_{env}.json")
                        shutil.copy("captures/jhs_state_session_storage.json", f"captures/jhs_state_{env}_session_storage.json")
                        print(f"[Jio Humsafar Loop] Primed environment-scoped session for '{env}'", flush=True)
                    except Exception:
                        pass
                        
                self.success = True
                self.login_result_event.set()
            else:
                if not self.error:
                    self.error = "Login session timed out or browser window was closed."
                self.login_result_event.set()
                
        except Exception as e:
            print(f"[Jio Humsafar Loop] General error in background loop: {e}", flush=True)
            self.error = f"Login failed: {e}"
            self.login_result_event.set()
        finally:
            print("[Jio Humsafar Loop] Cleaning up background browser context.", flush=True)
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
        print(f"[Jio Humsafar Manager] Terminating background login session {self.id}.", flush=True)
        self.is_alive = False
        
jhs_active_sessions = {}
