from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from pathlib import Path
import logging
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from db.database import create_db_and_tables
from api.routes import auth, users, websocket, geocoding, bounces, notifications, checkins
from api.routes.websocket import manager as ws_manager
# Instagram 2FA - uncomment when ready to use
# from api.routes import instagram_verify
# from services.instagram_2fa import start_ig_poller, stop_ig_poller
from api.dependencies import limiter
from services.redis import close_redis
from core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Set specific log levels
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # Reduce noise from access logs
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # Reduce SQL query logs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    await create_db_and_tables()
    # Start WebSocket Redis subscriber
    await ws_manager.start_subscriber()
    # Instagram 2FA poller - uncomment when ready to use
    # await start_ig_poller()
    yield
    # Cleanup
    # await stop_ig_poller()
    await close_redis()


app = FastAPI(
    title="Art Basel Miami API",
    description="Micro social media for Art Basel Miami",
    version="1.0.0",
    lifespan=lifespan
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware for WebSocket and HTTP connections
# Configure based on environment (development vs production)
allowed_origins = settings.ALLOWED_ORIGINS.split(",") if hasattr(settings, "ALLOWED_ORIGINS") and settings.ALLOWED_ORIGINS else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Use environment-specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Create upload directory
uploads_dir = Path(settings.UPLOAD_DIR)
uploads_dir.mkdir(exist_ok=True)
app.mount("/files", StaticFiles(directory=settings.UPLOAD_DIR), name="files")

# Include routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(websocket.router)
app.include_router(geocoding.router)
app.include_router(bounces.router)
app.include_router(notifications.router)
app.include_router(checkins.router)
# app.include_router(instagram_verify.router)  # Uncomment when ready to use


@app.get("/")
async def root():
    return {"message": "Art Basel Miami API", "status": "running"}


@app.get("/health")
async def health():
    from services.redis import get_redis

    redis_ok = False
    try:
        redis = await get_redis()
        await redis.ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status": "healthy",
        "redis": "connected" if redis_ok else "disconnected"
    }
