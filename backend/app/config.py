import os
from dotenv import load_dotenv

load_dotenv()

# Get the absolute path to the database file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_FILE = os.path.join(BASE_DIR, "database", "email_automation.db")

# Create database directory if it doesn't exist
os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

class Settings:
    # Google OAuth2
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")

    # Application
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    SCHEDULER_SECRET: str = os.getenv("SCHEDULER_SECRET", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DB_FILE}")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:8081")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    CORS_ORIGINS_RAW: str = os.getenv("CORS_ORIGINS", "")
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")

    # Email settings
    MAX_EMAILS_PER_DAY: int = int(os.getenv("MAX_EMAILS_PER_DAY", "30"))
    MIN_DELAY_MINUTES: int = int(os.getenv("MIN_DELAY_MINUTES", "2"))
    MAX_DELAY_MINUTES: int = int(os.getenv("MAX_DELAY_MINUTES", "7"))

    # Development mode - enable test email sending without Gmail auth
    DEV_MODE: bool = os.getenv("DEV_MODE", "false").lower() == "true"
    TEST_EMAIL_INBOX: str = os.getenv("TEST_EMAIL_INBOX", "/tmp/sendflow_emails")
    
    # Tracking
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")
    EMAIL_TRACKING_ENABLED: bool = os.getenv("EMAIL_TRACKING_ENABLED", "true").lower() == "true"

    @property
    def CORS_ORIGINS(self):
        default_origins = [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:8081",
            "http://127.0.0.1:8081",
            "http://localhost:8082",
            "http://127.0.0.1:8082",
            "http://localhost:8501",
            "http://127.0.0.1:8501",
            "http://localhost:3000",
            "http://localhost:5173",
        ]
        configured = [
            origin.strip()
            for origin in self.CORS_ORIGINS_RAW.split(",")
            if origin.strip()
        ]
        if self.FRONTEND_URL:
            configured.append(self.FRONTEND_URL.strip())
        # preserve order, remove duplicates
        return list(dict.fromkeys(default_origins + configured))

settings = Settings()
