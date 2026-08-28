import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
    SLOW_MO = int(os.getenv("SLOW_MO", 30))
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 4))
    
    PROXY_LIST = [p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()]
    TWOCAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")
    PROFILES_DIR = os.getenv("PROFILES_DIR", "./profiles")
    DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    WATCH_INTERVAL_MIN_SECONDS = int(os.getenv("WATCH_INTERVAL_MIN_SECONDS", 600))
    WATCH_INTERVAL_MAX_SECONDS = int(os.getenv("WATCH_INTERVAL_MAX_SECONDS", 1200))
    ERROR_BACKOFF_MIN_SECONDS = int(os.getenv("ERROR_BACKOFF_MIN_SECONDS", 1800))
    ERROR_BACKOFF_MAX_SECONDS = int(os.getenv("ERROR_BACKOFF_MAX_SECONDS", 3600))
    CHALLENGE_ALERT_COOLDOWN_SECONDS = int(
        os.getenv("CHALLENGE_ALERT_COOLDOWN_SECONDS", 1800)
    )
    SEEN_OFFERS_FILE = os.getenv(
        "SEEN_OFFERS_FILE",
        os.getenv("SEEN_ITEMS_FILE", "./seen_offers.json"),
    )
    OFFERS_FILE = os.getenv("OFFERS_FILE", "./offers.json")
    DASHBOARD_FILE = os.getenv("DASHBOARD_FILE", "./dashboard.json")
    LINK_SERVER_HOST = os.getenv("LINK_SERVER_HOST", "127.0.0.1")
    LINK_SERVER_PORT = int(os.getenv("LINK_SERVER_PORT", 8765))
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    OPEN_OFFERS_IN_CLIENT = os.getenv("OPEN_OFFERS_IN_CLIENT", "false").lower() == "true"
    INSTRUCTIONS_FILE = os.getenv("INSTRUCTIONS_FILE", "./instructions.yaml")
    SEARCH_STATUS_FILE = os.getenv("SEARCH_STATUS_FILE", "./search_status.json")