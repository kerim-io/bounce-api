from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path

from db.database import create_db_and_tables
from api.routes import auth, posts, users, checkins, websocket, likes, geocoding
from core.config import settings


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


@app.get("/")
async def root():
    return {"message": "Art Basel Miami API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
