import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

class Settings:
    # Railway provides DATABASE_URL as postgresql://, we need to convert to postgresql+asyncpg://
    _db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://kerim@localhost:5432/artbasel_db")
    DATABASE_URL: str = _db_url.replace("postgresql://", "postgresql+asyncpg://") if _db_url.startswith("postgresql://") else _db_url

    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))  # 1 hour
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "3650"))  # 10 years - never expire unless explicit logout

    # Auth passcode (for development/testing)
    AUTH_PASSCODE: str = os.getenv("AUTH_PASSCODE", "ARTBASEL2024")

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024)))

    # Apple Sign In
    APPLE_TEAM_ID: str = os.getenv("APPLE_TEAM_ID", "")
    APPLE_KEY_ID: str = os.getenv("APPLE_KEY_ID", "")
    APPLE_CLIENT_ID: str = os.getenv("APPLE_CLIENT_ID", "com.theappagency.lit")
    APPLE_REDIRECT_URI: str = os.getenv("APPLE_REDIRECT_URI", "https://yourapp.com/auth/callback")

    # Geofence
    BASEL_LAT: float = float(os.getenv("BASEL_LAT", "25.7907"))
    BASEL_LON: float = float(os.getenv("BASEL_LON", "-80.1300"))
    BASEL_RADIUS_KM: float = float(os.getenv("BASEL_RADIUS_KM", "5"))

    # Activity Clustering (for map hotspots)
    ACTIVITY_CLUSTER_RADIUS_M: float = float(os.getenv("ACTIVITY_CLUSTER_RADIUS_M", "100"))  # meters
    ACTIVITY_TIME_WINDOW_MIN: int = int(os.getenv("ACTIVITY_TIME_WINDOW_MIN", "60"))  # minutes

    # QR Code
    QR_SECRET_SALT: str = os.getenv("QR_SECRET_SALT", "change-this-qr-salt-in-production")
    # Use HTTPS URL so any phone can scan and open in browser (which redirects to app)
    QR_DEEP_LINK_SCHEME: str = os.getenv("QR_DEEP_LINK_SCHEME", "https://baselradar.app/connect/")

    # Google Maps API
    GOOGLE_MAPS_API_KEY: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # Groq (AI commentator)
    GROQ_API_KEY: str = os.getenv("GROQ", "")

    # Base URL for share links
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # APNs (Apple Push Notification Service)
    # Falls back to APPLE_KEY_BASE64 if APNS_KEY_BASE64 not set
    APNS_KEY_BASE64: str = os.getenv("APNS_KEY_BASE64", "") or os.getenv("APPLE_KEY_BASE64", "")
    APNS_KEY_ID: str = os.getenv("APNS_KEY_ID", "")  # Key ID from Apple Developer
    APNS_TEAM_ID: str = os.getenv("APNS_TEAM_ID", "") or os.getenv("APPLE_TEAM_ID", "")  # Team ID
    APNS_BUNDLE_ID: str = os.getenv("APNS_BUNDLE_ID", "com.theappagency.lit")  # App bundle ID
    APNS_USE_SANDBOX: bool = os.getenv("APNS_USE_SANDBOX", "false").lower() == "true"

    # Instagram 2FA Verification
    IG_USERNAME: str = os.getenv("IG_USERNAME", "")
    IG_PASSWORD: str = os.getenv("IG_PASSWORD", "")
    IG_POLL_INTERVAL: int = int(os.getenv("IG_POLL_INTERVAL", "45"))  # seconds
    IG_VERIFICATION_TTL: int = int(os.getenv("IG_VERIFICATION_TTL", "86400"))  # 24 hours

settings = Settings()
