import os
import json
import time
from urllib.parse import urlparse
from playwright.sync_api import Browser, BrowserContext, Page
from jio_auth.config import get_session_paths, SESSION_REFRESH_MARGIN_MS, JIO_HUMSAFAR_PROD_URL

# Setup Logging
import logging
logger = logging.getLogger("JioHumsafarAuth.SessionManager")

def check_session_valid_offline(email: str) -> bool:
    """
    Zero-network offline check: reads the token expiration from the saved sessionStorage
    file to check if the session is valid, without making any network requests.
    """
    paths = get_session_paths(email)
    state_file = paths["state_json"]
    ss_file = paths["session_storage_json"]
    
    if not os.path.exists(state_file) or not os.path.exists(ss_file):
        logger.info(f"[OFFLINE] No saved session state found for {email}.")
        return False
        
    try:
        with open(ss_file, "r", encoding="utf-8") as f:
            ss_data = json.load(f)
            
        # Check standard JioHumsafar expiration keys
        exp_str = ss_data.get("ASSET_TOKEN_EXP") or ss_data.get("authTokenKey")
        if exp_str:
            exp_ms = float(exp_str)
            current_ms = time.time() * 1000
            
            # Deduct the 5-minute safety margin
            remaining_ms = exp_ms - current_ms
            if remaining_ms > SESSION_REFRESH_MARGIN_MS:
                logger.info(f"[OFFLINE] Session is VALID for {email}. Expires in {int(remaining_ms / 1000)}s.")
                return True
            else:
                logger.info(f"[OFFLINE] Session is EXPIRED or close to expiring for {email}.")
                return False
        else:
            logger.warning(f"[OFFLINE] Token expiration key not found in storage for {email}.")
            return False
            
    except Exception as e:
        logger.error(f"[OFFLINE] Error reading session storage file: {e}")
        return False

def check_session_valid_online(browser: Browser, email: str, base_url: str = JIO_HUMSAFAR_PROD_URL) -> bool:
    """
    Online check fallback: Spawns a temporary browser context, navigates to the protected
    dashboard, and checks if it remains on the dashboard or gets redirected to the login page.
    """
    paths = get_session_paths(email)
    state_file = paths["state_json"]
    
    if not os.path.exists(state_file):
        return False
        
    context = None
    page = None
    try:
        # Launch isolated validation context
        context = browser.new_context(storage_state=state_file)
        inject_session_storage(context, email)
        page = context.new_page()
        
        dashboard_url = base_url.rstrip("/") + "/#/pages/dashboard/aggregate-dashboard"
        logger.info(f"[ONLINE] Verifying session online at {dashboard_url}...")
        
        page.goto(dashboard_url, wait_until="domcontentloaded", timeout=12000)
        
        # Check for presence of dashboard indicators (avoiding auth redirects)
        try:
            page.wait_for_selector(".sidebar-link, a[href*='dashboard'], .main-header, app-donut-chart", timeout=5000)
            curr_url = page.url.lower()
            if "login" not in curr_url and "auth" not in curr_url:
                logger.info(f"[ONLINE] Session verified successfully online for {email}.")
                return True
        except Exception:
            pass
            
        logger.info(f"[ONLINE] Session is invalid or redirected to login screen for {email}.")
        return False
        
    except Exception as e:
        logger.error(f"[ONLINE] Session validation failed with exception: {e}")
        return False
        
    finally:
        if page:
            try: page.close()
            except Exception: pass
        if context:
            try: context.close()
            except Exception: pass

def inject_session_storage(context: BrowserContext, email: str):
    """Inject sessionStorage keys using an init script before any document loads."""
    paths = get_session_paths(email)
    ss_file = paths["session_storage_json"]
    
    if os.path.exists(ss_file):
        try:
            with open(ss_file, "r", encoding="utf-8") as f:
                ss_data = json.load(f)
                
            # Playwright init script injection
            script = f"""
            (() => {{
                const data = {json.dumps(ss_data)};
                for (const [k, v] of Object.entries(data)) {{
                    window.sessionStorage.setItem(k, v);
                }}
            }})();
            """
            context.add_init_script(script)
            logger.info(f"[SESSION] Successfully injected sessionStorage for {email}.")
        except Exception as e:
            logger.error(f"[SESSION] Failed to inject sessionStorage script: {e}")

def save_browser_session(page: Page, email: str):
    """Captures cookies, localStorage, and sessionStorage, persisting them to disk."""
    paths = get_session_paths(email)
    state_file = paths["state_json"]
    ss_file = paths["session_storage_json"]
    
    try:
        # Save cookies & localStorage
        page.context.storage_state(path=state_file)
        logger.info(f"[SESSION] Cookies and localStorage saved to {state_file}")
        
        # Evaluate and save sessionStorage
        ss_raw = page.evaluate("() => JSON.stringify(window.sessionStorage)")
        ss_dict = json.loads(ss_raw)
        
        with open(ss_file, "w", encoding="utf-8") as f:
            json.dump(ss_dict, f, indent=4)
            
        logger.info(f"[SESSION] sessionStorage successfully saved to {ss_file}")
        
    except Exception as e:
        logger.error(f"[SESSION] Failed to capture and save browser session: {e}")
