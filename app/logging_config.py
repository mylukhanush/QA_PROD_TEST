import os
import sys
import json
import logging
from datetime import datetime, timezone

# Global logger setup
LOGGER_NAME = "qa_agent"
LOG_FILE_PATH = os.path.join("instance", "app.log")

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
        return json.dumps(log_entry)

def configure_logging(app=None):
    os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
    
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return
        
    # File Handler for structured JSON logs
    file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
    file_handler.setFormatter(JSONFormatter())
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    # Stream Handler for human-readable console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_format = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
    )
    console_handler.setFormatter(console_format)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

def log_event(event, **fields):
    """
    Log an event with extra fields. Strips sensitive info like passwords, credentials, and OTP keys.
    """
    clean_fields = {}
    sensitive_keys = {"password", "username", "otp", "otp_secret", "secret", "credential", "credentials", "token"}
    
    for k, v in fields.items():
        if k.lower() in sensitive_keys:
            clean_fields[k] = "[REDACTED]"
        elif k in ("situation_description", "user_prompt") and v:
            clean_fields[k] = (str(v)[:200] + "...") if len(str(v)) > 200 else str(v)
        else:
            clean_fields[k] = v
            
    logger = logging.getLogger(LOGGER_NAME)
    extra = {"extra_fields": {"event": event, **clean_fields}}
    logger.info(f"Event: {event}", extra=extra)
