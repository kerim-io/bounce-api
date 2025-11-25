from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path
import logging

from db.database import create_db_and_tables
from api.routes import auth, posts, users, checkins, websocket, likes, geocoding, locations, livestream, bounces
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
    yield


app = FastAPI(
    title="Art Basel Miami API",
    description="Micro social media for Art Basel Miami",
    version="1.0.0",
    lifespan=lifespan
)

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
app.include_router(posts.router)
app.include_router(users.router)
app.include_router(checkins.router)
app.include_router(websocket.router)
app.include_router(likes.router)
app.include_router(geocoding.router)
app.include_router(locations.router)
app.include_router(livestream.router)
app.include_router(bounces.router)


@app.get("/")
async def root():
    return {"message": "Art Basel Miami API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
