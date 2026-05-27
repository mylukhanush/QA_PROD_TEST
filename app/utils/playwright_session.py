import os
import time
import json
import shutil
from urllib.parse import urlparse
from playwright.sync_api import Browser

def get_shared_session_path(env_name: str, email: str = None) -> str:
    """Retrieve the file path for the environment-scoped session storage state."""
    os.makedirs("captures", exist_ok=True)
    env_clean = env_name.lower().strip()
    if email:
        safe_email = email.lower().strip().replace("@", "_").replace(".", "_")
        return f"captures/jhs_state_{env_clean}_{safe_email}.json"
    return f"captures/jhs_state_{env_clean}.json"

def inject_session_storage_to_context(context, env_name: str, email: str = None):
    """
    Read the environment-scoped sessionStorage JSON, and inject it as an init script
    into the browser context so it is restored before any page loads.
    """
    state_file = get_shared_session_path(env_name, email)
    ss_file = state_file.replace(".json", "_session_storage.json")
    if not os.path.exists(ss_file):
        ss_file = "captures/jhs_state_session_storage.json"
        
    if os.path.exists(ss_file):
        try:
            with open(ss_file, "r", encoding="utf-8") as f:
                ss_data = json.load(f)
            # Inject a script to populate sessionStorage before the Angular app loads
            script = f"""
            (() => {{
                const data = {json.dumps(ss_data)};
                for (const [k, v] of Object.entries(data)) {{
                    window.sessionStorage.setItem(k, v);
                }}
            }})();
            """
            context.add_init_script(script)
            print(f"[SESSION UTILS] Successfully injected sessionStorage restoration script for '{env_name}' (Email: {email})", flush=True)
        except Exception as e:
            print(f"[SESSION UTILS] Failed to inject sessionStorage for '{env_name}': {e}", flush=True)

def adapt_master_session_to_env(env_name: str, base_url: str, email: str = None):
    """
    Read the master session file captures/jhs_state.json,
    and dynamically rewrite its localStorage origins and cookie domains
    to match the current target site's base_url.
    Saves the adapted session state to captures/jhs_state_<env_name>_<email>.json.
    Also copies the sessionStorage companion file.
    """
    master_file = "captures/jhs_state.json"
    target_file = get_shared_session_path(env_name, email)
    
    if not os.path.exists(master_file):
        print(f"[SESSION UTILS] Master session '{master_file}' not found. Cannot adapt.", flush=True)
        return
        
    try:
        with open(master_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            
        # Parse target scheme, host and port
        parsed = urlparse(base_url)
        target_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip('/')
        target_host = parsed.hostname or ""
        
        # 1. Update cookies domain to match target host
        if "cookies" in state and isinstance(state["cookies"], list):
            for cookie in state["cookies"]:
                cookie["domain"] = target_host
                
        # 2. Update localStorage origins to match target origin URL
        if "origins" in state and isinstance(state["origins"], list):
            for entry in state["origins"]:
                entry["origin"] = target_origin
                
        # Write the adapted state
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
            
        print(f"[SESSION UTILS] Successfully adapted master session to '{env_name}' (Email: {email}, Origin: {target_origin})", flush=True)
        
        # Copy sessionStorage companion file too
        master_ss = "captures/jhs_state_session_storage.json"
        target_ss = target_file.replace(".json", "_session_storage.json")
        if os.path.exists(master_ss):
            shutil.copy(master_ss, target_ss)
            print(f"[SESSION UTILS] Copied companion sessionStorage for '{env_name}' (Email: {email})", flush=True)
            
    except Exception as e:
        print(f"[SESSION UTILS] Failed to adapt master session to '{env_name}': {e}", flush=True)

def check_session_valid(browser: Browser, env_name: str, base_url: str, email: str = None) -> bool:
    """
    Verify if a saved session state is valid.
    First checks the session expiration offline (using ASSET_TOKEN_EXP key).
    If offline check passes, returns True without making any web requests.
    Otherwise, falls back to the online page navigation check.
    """
    state_file = get_shared_session_path(env_name, email)
    if not os.path.exists(state_file):
        return False
        
    # Offline Session Expiration Verification (Zero-Network check)
    ss_file = state_file.replace(".json", "_session_storage.json")
    if not os.path.exists(ss_file):
        ss_file = "captures/jhs_state_session_storage.json"
        
    if os.path.exists(ss_file):
        try:
            with open(ss_file, "r", encoding="utf-8") as f:
                ss_data = json.load(f)
            exp_str = ss_data.get("ASSET_TOKEN_EXP") or ss_data.get("authTokenKey")
            if exp_str:
                exp_ms = float(exp_str)
                current_ms = time.time() * 1000
                # Safety margin of 5 minutes (300,000 milliseconds)
                if current_ms < (exp_ms - 300000):
                    print(f"[SESSION UTILS] [OFFLINE CHECK] Session for '{env_name}' ({email}) is VALID. Expires in {int((exp_ms - current_ms)/1000)}s. Skipping browser request.", flush=True)
                    return True
                else:
                    print(f"[SESSION UTILS] [OFFLINE CHECK] Session for '{env_name}' ({email}) is EXPIRED or close to expiring.", flush=True)
        except Exception as e:
            print(f"[SESSION UTILS] Offline session validation failed: {e}", flush=True)

    # Fallback to Online browser validation check if offline check is inconclusive or expired
    context = None
    page = None
    try:
        context = browser.new_context(storage_state=state_file)
        # Inject the sessionStorage!
        inject_session_storage_to_context(context, env_name, email)
        page = context.new_page()
        
        # Go to a protected page (the aggregate dashboard)
        dashboard_url = base_url.rstrip('/') + "/#/pages/dashboard/aggregate-dashboard"
        print(f"[SESSION UTILS] Verifying session validity online for '{env_name}' ({email}) at {dashboard_url}...", flush=True)
        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=12000)
        
        # Wait up to 5s to see if a sidebar link or dashboard element becomes visible
        try:
            page.wait_for_selector(".sidebar-link, a[href*='dashboard'], .main-header, app-donut-chart, .dashboard-widget-grid", timeout=5000)
            curr_url = page.url.lower()
            if "login" not in curr_url and "auth" not in curr_url:
                print(f"[SESSION UTILS] Session for '{env_name}' ({email}) is VALID online.", flush=True)
                return True
        except Exception:
            pass
            
        print(f"[SESSION UTILS] Session for '{env_name}' ({email}) is EXPIRED or INVALID online.", flush=True)
        return False
    except Exception as e:
        print(f"[SESSION UTILS] Error verifying session validity for '{env_name}' ({email}): {e}", flush=True)
        return False
    finally:
        if page:
            try: page.close()
            except Exception: pass
        if context:
            try: context.close()
            except Exception: pass

def get_or_create_session(browser: Browser, env_name: str, base_url: str, credentials: dict, login_info: dict) -> str:
    """
    Get the path to a valid environment-scoped session state file.
    Checks validity first. If invalid/missing, triggers login once, saves, and returns path.
    """
    email = credentials.get("username")
    
    # 0. Adapt from master session first to see if we can reuse the active opening login
    adapt_master_session_to_env(env_name, base_url, email)
    
    state_file = get_shared_session_path(env_name, email)
    
    # 1. Reuse existing valid session if available
    if check_session_valid(browser, env_name, base_url, email):
        return state_file
        
    # 2. Expired or missing: perform login once, save storage state, then return path
    print(f"[SESSION UTILS] Valid session missing/expired for '{env_name}' ({email}). Running one-time login...", flush=True)
    
    context = None
    page = None
    try:
        context = browser.new_context()
        page = context.new_page()
        
        login_url = base_url.rstrip('/') + "/#/auth/login"
        print(f"[SESSION UTILS] Navigating to login page: {login_url}", flush=True)
        page.goto(login_url, wait_until="networkidle")
        
        # Click landing splash page Login button if visible
        try:
            landing_login_btn = page.locator('button:has-text("Login"), a:has-text("Login"), .login-btn').first
            if landing_login_btn.is_visible():
                print("[SESSION UTILS] Landing page detected. Clicking 'Login' button...", flush=True)
                landing_login_btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass
            
        username_sel = login_info.get("username_selector", "input[formcontrolname=\"username\"]")
        password_sel = login_info.get("password_selector", "input#password-field")
        submit_sel = login_info.get("submit_selector", "button.login_btn")
        
        # Fill username
        page.locator(username_sel).first.wait_for(state="visible", timeout=15000)
        page.locator(username_sel).first.fill(credentials.get("username", ""))
        
        # Fill password
        page.locator(password_sel).first.fill(credentials.get("password", ""))
        
        # Click login button to request OTP
        page.locator(submit_sel).first.click()
        
        # Wait for OTP input field to appear
        otp_sel = 'input#otp_Email:visible, input[id*="otp"]:visible, input[name="otp"]:visible'
        page.locator(otp_sel).first.wait_for(state="visible", timeout=10000)
        
        # Prompt in CLI/console fallback for OTP if not interactive
        otp_code = input(f"\n[SESSION UTILS JHS OTP] Please enter the OTP sent to {email}: ").strip()
        
        page.locator(otp_sel).first.fill(otp_code)
        page.locator(submit_sel).first.click()
        
        # Wait for successful dashboard load
        print("[SESSION UTILS] Submitting OTP and waiting for successful redirect...", flush=True)
        page.wait_for_function(
            """() => window.location.href.includes('#/pages/dashboard/') || 
                     document.querySelector('.sidebar-link, a[href*="dashboard"], .main-header') !== null""",
            timeout=25000
        )
        
        # Wait for single page app storage to fully settle before saving
        page.wait_for_timeout(4000)
        
        # Save storage state
        context.storage_state(path=state_file)
        
        # Save sessionStorage manually
        try:
            ss_data = page.evaluate("() => JSON.stringify(window.sessionStorage)")
            ss_dict = json.loads(ss_data)
            ss_file = state_file.replace(".json", "_session_storage.json")
            with open(ss_file, "w", encoding="utf-8") as f:
                json.dump(ss_dict, f)
            print(f"[SESSION UTILS] sessionStorage successfully saved to {ss_file}", flush=True)
            
            # Copy to master too
            with open("captures/jhs_state_session_storage.json", "w", encoding="utf-8") as f:
                json.dump(ss_dict, f)
        except Exception as e:
            print(f"[SESSION UTILS] Failed to save sessionStorage: {e}", flush=True)
            
        print(f"[SESSION UTILS] Session successfully generated and saved to: {state_file}", flush=True)
        
        # Also copy this back to master session captures/jhs_state.json to keep it updated!
        try:
            context.storage_state(path="captures/jhs_state.json")
            print("[SESSION UTILS] Successfully updated master session captures/jhs_state.json", flush=True)
        except Exception:
            pass
            
        return state_file
        
    except Exception as e:
        print(f"[SESSION UTILS] One-time login failed for '{env_name}' ({email}): {e}", flush=True)
        raise e
    finally:
        if page:
            try: page.close()
            except Exception: pass
        if context:
            try: context.close()
            except Exception: pass
