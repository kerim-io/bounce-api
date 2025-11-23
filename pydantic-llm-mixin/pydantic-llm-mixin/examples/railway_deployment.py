"""
Railway Deployment Example - Bookstore Generator

Generate a complete bookstore with inventory using discriminated unions.
Includes JWT authentication.
"""

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerationError, GenerativeMixin, get_groq_client

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Security
security = HTTPBearer()

# Global client
groq_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global groq_client

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    groq_client = await get_groq_client(api_key=api_key, temperature=0.6, max_tokens=3000)
    print("✅ Groq client initialized")

    yield

    if groq_client:
        await groq_client.close()


app = FastAPI(title="Bookstore Generator API", lifespan=lifespan)


# ============================================================================
# AUTH MODELS
# ============================================================================


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class User(BaseModel):
    username: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


# ============================================================================
# AUTH FUNCTIONS
# ============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Verify JWT token and return current user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    # In production, look up user from database
    # For demo, return mock user
    if token_data.username is None:
        raise credentials_exception
    user = User(username=token_data.username, email=f"{token_data.username}@example.com")
    return user


# ============================================================================
# BOOKSTORE MODELS
# ============================================================================


class Book(BaseModel):
    """A book"""

    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    isbn: str = Field(..., description="ISBN")
    price: float = Field(..., description="Price in dollars")
    pages: int = Field(..., description="Number of pages")


class DVD(BaseModel):
    """A DVD"""

    title: str = Field(..., description="DVD title")
    director: str = Field(..., description="Director")
    runtime_minutes: int = Field(..., description="Runtime in minutes")
    price: float = Field(..., description="Price in dollars")
    rating: Literal["G", "PG", "PG-13", "R", "NC-17"] = Field(..., description="Rating")


class Poster(BaseModel):
    """A poster"""

    title: str = Field(..., description="Poster title")
    artist: str = Field(..., description="Artist")
    dimensions: str = Field(..., description="Dimensions like '24x36 inches'")
    price: float = Field(..., description="Price in dollars")
    material: Literal["paper", "canvas", "vinyl"] = Field(..., description="Material")


# Discriminated union
BookstoreItem = Book | DVD | Poster


class Bookstore(BaseModel, GenerativeMixin):
    """A bookstore with inventory"""

    name: str = Field(..., description="Bookstore name")
    location: str = Field(..., description="City and country")
    specialty: str = Field(..., description="What the store specializes in")
    inventory: list[BookstoreItem] = Field(..., description="Items in stock (Books, DVDs, Posters)")


class GenerateRequest(BaseModel):
    """Request to generate a bookstore"""

    query: str = Field(..., description="Describe the bookstore")


class GenerateResponse(BaseModel):
    """Response with generated bookstore"""

    bookstore: Bookstore
    success: bool = True


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================


@app.post("/auth/login", response_model=Token)
async def login(request: LoginRequest):
    """
    Login to get JWT token.

    Demo credentials: username=demo, password=demo
    """
    # Demo user - in production, verify against database
    if request.username == "demo" and request.password == "demo":
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": request.username}, expires_delta=access_token_expires
        )
        return Token(access_token=access_token, token_type="bearer")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return current_user


# ============================================================================
# BOOKSTORE ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "healthy",
        "service": "Bookstore Generator API",
        "auth": "JWT Bearer token required for /generate endpoint"
    }


@app.post("/generate", response_model=GenerateResponse)
async def generate_bookstore(
    request: GenerateRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Generate a bookstore from natural language.

    Requires JWT authentication. Get token from /auth/login first.

    Example: {"query": "Create a bookstore in Paris"}
    """
    try:
        conversation = [{"role": "user", "content": request.query}]

        bookstore = await Bookstore.generate_instance(
            client=groq_client,
            conversation_history=conversation,
        )

        return GenerateResponse(bookstore=bookstore)

    except GenerationError as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
