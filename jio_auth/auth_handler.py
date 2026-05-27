import os
from playwright.sync_api import Browser, BrowserContext
from jio_auth.config import get_session_paths, JIO_HUMSAFAR_PROD_URL
from jio_auth.session_manager import (
    check_session_valid_offline,
    check_session_valid_online,
    inject_session_storage
)
from jio_auth.login import perform_interactive_login

# Setup Logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join("reports", "auth_logs", "jhs_auth.log"), encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("JioHumsafarAuth.Orchestrator")

def get_authenticated_context(browser: Browser, email: str, base_url: str = JIO_HUMSAFAR_PROD_URL) -> BrowserContext:
    """
    Orchestrates the entire authentication flow for a given linked email ID:
    1. First, runs the zero-network offline token check.
    2. If offline check fails, falls back to the online browser verification check.
    3. If online check fails, executes the interactive login/OTP submission.
    4. Upon login success, returns a pre-configured, pre-authenticated BrowserContext.
    """
    email = email.lower().strip()
    paths = get_session_paths(email)
    state_file = paths["state_json"]
    
    logger.info(f"--- Initiating JHS Authentication Orchestration for: {email} ---")
    
    # Step 1: Zero-Network Offline Validation
    session_valid = check_session_valid_offline(email)
    
    # Step 2: Fallback to Online Browser Check if offline check was inconclusive
    if not session_valid:
        logger.info(f"[ORCHESTRATOR] Offline check invalid. Launching online browser validation for {email}...")
        session_valid = check_session_valid_online(browser, email, base_url)
        
    # Step 3: Trigger Fresh interactive Login/OTP flow if session is expired
    if not session_valid:
        logger.warning(f"[ORCHESTRATOR] Session is EXPIRED or MISSING for {email}. Triggering login recovery...")
        login_success = perform_interactive_login(browser, email, base_url)
        if not login_success:
            raise Exception(f"Failed to authenticate JioHumsafar account: {email}. See logs/screenshots for details.")
            
    # Step 4: Construct and Return the Pre-Authenticated Context
    logger.info(f"[ORCHESTRATOR] Session is verified. Creating authenticated context for {email}...")
    
    # Create context using the saved state JSON (restores cookies and localStorage)
    context = browser.new_context(
        storage_state=state_file,
        viewport={"width": 1280, "height": 720}
    )
    
    # Inject sessionStorage variables (restores tokens and Angular states)
    inject_session_storage(context, email)
    
    logger.info(f"[ORCHESTRATOR] Successfully established 8-hour session context for {email}!")
    return context
