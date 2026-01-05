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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "365"))  # 1 year

    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(10 * 1024 * 1024)))

    # Apple Sign In
    APPLE_TEAM_ID: str = os.getenv("APPLE_TEAM_ID", "")
    APPLE_KEY_ID: str = os.getenv("APPLE_KEY_ID", "")
    APPLE_CLIENT_ID: str = os.getenv("APPLE_CLIENT_ID", "com.yourapp.artbasel")
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

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

settings = Settings()
