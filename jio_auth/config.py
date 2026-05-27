import os
from dotenv import load_dotenv

# Load workspace environment variables
load_dotenv()

# Production target URLs
JIO_HUMSAFAR_PROD_URL = os.getenv("JIO_HUMSAFAR_PROD_URL", "https://jiohumsafar.jio.com/").strip()

# Default directory for persistent credentials/states
SESSION_CAPTURE_DIR = os.path.join("captures", "prod_sessions")
os.makedirs(SESSION_CAPTURE_DIR, exist_ok=True)

# Logs Directory
LOGS_DIR = os.path.join("reports", "auth_logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# Screenshots Directory for debugging
SCREENSHOTS_DIR = os.path.join(os.getenv("SCREENSHOTS_DIR", "screenshots"), "prod_auth")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# Headless mode config: Defaults to False initially for easy headful login/OTP debugging
BROWSER_HEADLESS = os.getenv("JHS_BROWSER_HEADLESS", "False").lower() in ("true", "1", "yes")

# Token lifespan safety margins (in milliseconds)
SESSION_REFRESH_MARGIN_MS = 300000  # 5 minutes safety margin for offline validation

def get_account_credentials(email: str) -> dict:
    """
    Retrieve credentials dynamically for multiple linked email IDs.
    Looks for matching env variables like:
    ranjit@assettl.com -> JHS_ranjit_assettl_PASSWORD
    Or falls back to JHS83_USERNAME/PASSWORD.
    """
    normalized_email = email.lower().strip()
    
    # Generate custom env var key
    env_safe_email = normalized_email.replace("@", "_").replace(".", "_").upper()
    password_env_key = f"JHS_{env_safe_email}_PASSWORD"
    
    password = os.getenv(password_env_key)
    
    # Fallback to standard JHS83 credentials if email matches default
    if not password and normalized_email == os.getenv("JHS83_USERNAME", "ranjit@assettl.com"):
        password = os.getenv("JHS83_PASSWORD", "Rjil@12345")
        
    if not password:
        password = os.getenv("JHS_DEFAULT_PASSWORD", "Rjil@12345")
        
    return {
        "username": normalized_email,
        "password": password
    }

def get_session_paths(email: str) -> dict:
    """Get the persistent state paths for a specific account email."""
    safe_name = email.lower().strip().replace("@", "_").replace(".", "_")
    return {
        "state_json": os.path.join(SESSION_CAPTURE_DIR, f"state_{safe_name}.json"),
        "session_storage_json": os.path.join(SESSION_CAPTURE_DIR, f"state_{safe_name}_session_storage.json")
    }
