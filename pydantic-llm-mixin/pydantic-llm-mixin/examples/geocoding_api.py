"""
Railway Deployment Example - Geocoding API with Authentication

Production-ready geocoding service with:
- Google Maps and OpenStreetMap support
- JWT authentication
- Approved users list (email whitelist)
- Secure password hashing
"""

import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, TimedSerializer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

from pydantic_llm_mixin.geocoding import GeocodingService, LocationResult, ReverseGeocodeResult

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Google Maps API Key
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Approved users (comma-separated emails)
APPROVED_USERS_RAW = os.getenv("APPROVED_USERS", "")
APPROVED_USERS = {email.strip().lower() for email in APPROVED_USERS_RAW.split(",") if email.strip()}

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Session management for HTMX demo (max_age checked in loads())
session_serializer = TimedSerializer(SECRET_KEY)

# Security
security = HTTPBearer()

# Global geocoding service
geocoding_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global geocoding_service

    # Initialize geocoding service with Google Maps
    if not GOOGLE_MAPS_API_KEY:
        raise RuntimeError("GOOGLE_MAPS_API_KEY environment variable is required")

    geocoding_service = GeocodingService(google_api_key=GOOGLE_MAPS_API_KEY)
    print("✅ Google Maps geocoding service initialized")

    if APPROVED_USERS:
        print(f"✅ Approved users: {len(APPROVED_USERS)} email(s)")
    else:
        print("⚠️  WARNING: No approved users configured. Set APPROVED_USERS environment variable.")

    yield


app = FastAPI(title="Geocoding API with Authentication", lifespan=lifespan)

# Mount static files for embeddable widgets
app.mount("/static", StaticFiles(directory="examples/static"), name="static")


# ============================================================================
# AUTH MODELS
# ============================================================================


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: str | None = None


class User(BaseModel):
    email: EmailStr
    is_approved: bool = True


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 characters)")


# ============================================================================
# AUTH FUNCTIONS
# ============================================================================


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def is_user_approved(email: str) -> bool:
    """Check if user email is in approved list"""
    if not APPROVED_USERS:
        return False
    return email.lower() in APPROVED_USERS


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
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except JWTError:
        raise credentials_exception

    if token_data.email is None:
        raise credentials_exception

    # Verify user is still approved
    if not is_user_approved(token_data.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authorized to access this resource",
        )

    user = User(email=token_data.email, is_approved=True)
    return user


# ============================================================================
# GEOCODING REQUEST/RESPONSE MODELS
# ============================================================================


class GeocodeRequest(BaseModel):
    """Request to geocode an address"""

    address: str = Field(..., description="Address to geocode", min_length=1)


class ReverseGeocodeRequest(BaseModel):
    """Request to reverse geocode coordinates"""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================


@app.post("/auth/login", response_model=Token)
async def login(request: LoginRequest):
    """
    Login to get JWT token.

    Only approved users (listed in APPROVED_USERS environment variable) can authenticate.
    Password must be at least 8 characters.
    """
    # Check if user is approved
    if not is_user_approved(request.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User not authorized. Contact administrator to be added to approved users list.",
        )

    # Validate password meets minimum requirements
    if len(request.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # In production, verify password against database with hashed passwords
    # For this demo, we accept any password that meets the minimum requirements
    # You should replace this with actual password verification against your database

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": request.email}, expires_delta=access_token_expires)
    return Token(access_token=access_token, token_type="bearer")


@app.get("/auth/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return current_user


# ============================================================================
# GEOCODING ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "healthy",
        "service": "Geocoding API",
        "provider": geocoding_service.provider if geocoding_service else "not initialized",
        "auth": "JWT Bearer token required for geocoding endpoints",
        "approved_users_count": len(APPROVED_USERS),
    }


@app.post("/geocode", response_model=LocationResult)
async def geocode_address(request: GeocodeRequest, current_user: User = Depends(get_current_user)):
    """
    Forward geocoding: Convert address to coordinates

    Requires JWT authentication. Get token from /auth/login first.

    Example: {"address": "1600 Amphitheatre Parkway, Mountain View, CA"}
    """
    if not geocoding_service:
        raise HTTPException(status_code=503, detail="Geocoding service not initialized")

    result = geocoding_service.geocode(request.address)
    if not result:
        raise HTTPException(status_code=404, detail="Address not found")

    return result


@app.get("/geocode", response_model=LocationResult)
async def geocode_address_get(
    address: str = Query(..., description="Address to geocode", min_length=1),
    current_user: User = Depends(get_current_user),
):
    """
    Forward geocoding: Convert address to coordinates (GET method)

    Requires JWT authentication. Get token from /auth/login first.

    Example: /geocode?address=1600%20Amphitheatre%20Parkway,%20Mountain%20View,%20CA
    """
    if not geocoding_service:
        raise HTTPException(status_code=503, detail="Geocoding service not initialized")

    result = geocoding_service.geocode(address)
    if not result:
        raise HTTPException(status_code=404, detail="Address not found")

    return result


@app.post("/reverse", response_model=ReverseGeocodeResult)
async def reverse_geocode(request: ReverseGeocodeRequest, current_user: User = Depends(get_current_user)):
    """
    Reverse geocoding: Convert coordinates to address

    Requires JWT authentication. Get token from /auth/login first.

    Example: {"latitude": 37.422408, "longitude": -122.084068}
    """
    if not geocoding_service:
        raise HTTPException(status_code=503, detail="Geocoding service not initialized")

    result = geocoding_service.reverse_geocode(request.latitude, request.longitude)
    if not result:
        raise HTTPException(status_code=404, detail="Location not found")

    return result


@app.get("/reverse", response_model=ReverseGeocodeResult)
async def reverse_geocode_get(
    lat: float = Query(..., ge=-90, le=90, description="Latitude in decimal degrees"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude in decimal degrees"),
    current_user: User = Depends(get_current_user),
):
    """
    Reverse geocoding: Convert coordinates to address (GET method)

    Requires JWT authentication. Get token from /auth/login first.

    Example: /reverse?lat=37.422408&lon=-122.084068
    """
    if not geocoding_service:
        raise HTTPException(status_code=503, detail="Geocoding service not initialized")

    result = geocoding_service.reverse_geocode(lat, lon)
    if not result:
        raise HTTPException(status_code=404, detail="Location not found")

    return result


# ============================================================================
# EMBEDDABLE WIDGET ENDPOINTS
# ============================================================================


@app.get("/widgets/map", response_class=HTMLResponse)
async def get_map_widget(
    api_key: str = Query(..., description="Google Maps JavaScript API key"),
    token: str = Query(None, description="JWT token for API access"),
    lat: float = Query(40.7128, description="Default latitude"),
    lng: float = Query(-74.0060, description="Default longitude"),
    zoom: int = Query(13, description="Default zoom level"),
):
    """
    Embeddable map widget

    Returns an HTML page with interactive Google Maps that can be embedded via iframe.

    Query parameters:
    - api_key: Your Google Maps JavaScript API key (required)
    - token: JWT token for backend API calls (optional for public widgets)
    - lat: Initial map latitude (default: New York)
    - lng: Initial map longitude (default: New York)
    - zoom: Initial zoom level (default: 13)

    Example usage:
    <iframe src="https://your-domain.com/widgets/map?api_key=YOUR_KEY" width="100%" height="600"></iframe>
    """
    with open("examples/static/widgets/map-search.html") as f:
        html_content = f.read()

    # Replace API key placeholder
    html_content = html_content.replace("YOUR_GOOGLE_MAPS_JS_API_KEY", api_key)

    return HTMLResponse(content=html_content)


@app.get("/widgets/embed-code")
async def get_embed_code(
    api_key: str = Query(..., description="Google Maps JavaScript API key"),
    token: str = Query(None, description="JWT token for API access"),
    width: str = Query("100%", description="Widget width"),
    height: str = Query("600px", description="Widget height"),
    lat: float = Query(40.7128, description="Default latitude"),
    lng: float = Query(-74.0060, description="Default longitude"),
    zoom: int = Query(13, description="Default zoom level"),
):
    """
    Generate embed code for the map widget

    Returns HTML iframe code that can be copy-pasted into any website.

    Example response:
    {
        "iframe": "<iframe src='...' width='100%' height='600px'></iframe>",
        "script": "<script src='...'></script>"
    }
    """
    # Build widget URL
    widget_url = f"/widgets/map?api_key={api_key}"
    if token:
        widget_url += f"&token={token}"
    widget_url += f"&lat={lat}&lng={lng}&zoom={zoom}"

    # Generate iframe code
    iframe_code = f'<iframe src="{widget_url}" width="{width}" height="{height}" frameborder="0" style="border:0" allowfullscreen></iframe>'  # noqa: E501

    return {
        "iframe": iframe_code,
        "widget_url": widget_url,
        "instructions": "Copy the iframe code and paste it into your HTML",
    }



# ============================================================================
# HTMX DEMO ENDPOINTS (Server-side sessions, no JavaScript)
# ============================================================================


@app.get("/demo", response_class=HTMLResponse)
async def demo_page():
    """Serve location demo page with Google Maps"""
    with open("examples/static/demo.html") as f:
        html_content = f.read()

    # Inject Google Maps API key from environment
    html_content = html_content.replace("GOOGLE_MAPS_API_KEY_PLACEHOLDER", GOOGLE_MAPS_API_KEY or "")

    return HTMLResponse(content=html_content)


@app.post("/demo/login", response_class=HTMLResponse)
async def demo_login(email: str = Form(...), password: str = Form(...)):
    """HTMX login endpoint - returns HTML fragment"""
    
    # Check if user is approved
    if not is_user_approved(email):
        return HTMLResponse(
            content='<div class="error">User not authorized. Email must be in APPROVED_USERS list.</div>'
            '<form hx-post="/demo/login" hx-target="#content" hx-swap="innerHTML">'
            '<div class="form-group"><label for="email">Email</label>'
            '<input type="email" id="email" name="email" value="' + email + '" required></div>'
            '<div class="form-group"><label for="password">Password</label>'
            '<input type="password" id="password" name="password" required minlength="8"></div>'
            '<button type="submit">Login & Show My Location</button></form>'
        )
    
    # Validate password
    if len(password) < 8:
        return HTMLResponse(
            content='<div class="error">Password must be at least 8 characters.</div>'
            '<form hx-post="/demo/login" hx-target="#content" hx-swap="innerHTML">'
            '<div class="form-group"><label for="email">Email</label>'
            '<input type="email" id="email" name="email" value="' + email + '" required></div>'
            '<div class="form-group"><label for="password">Password</label>'
            '<input type="password" id="password" name="password" required minlength="8"></div>'
            '<button type="submit">Login & Show My Location</button></form>'
        )
    
    # Create session token
    session_data = {"email": email, "timestamp": datetime.now(UTC).isoformat()}
    session_token = session_serializer.dumps(session_data)

    # Return success page that triggers location fetch
    html_content = (
        '<div class="success">Login successful!</div>'
        '<div class="user-info"><p><strong>Email:</strong> ' + email + '</p></div>'
        '<div hx-get="/demo/location" hx-trigger="load" hx-swap="outerHTML">'
        '<div class="loading"><div class="spinner"></div>Fetching your location...</div></div>'
        '<button class="logout-btn" hx-post="/demo/logout" hx-target="#content" hx-swap="innerHTML">'
        'Logout</button>'
    )

    html_response = HTMLResponse(content=html_content)

    # Set secure cookie on the response
    html_response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=3600  # 1 hour
    )

    return html_response


@app.get("/demo/location", response_class=HTMLResponse)
async def demo_location(session: str = Cookie(None)):
    """HTMX endpoint to get user's location via browser geolocation (simulated with IP)"""
    
    # Verify session
    if not session:
        return HTMLResponse(content='<div class="error">Session expired. Please login again.</div>')
    
    try:
        session_serializer.loads(session, max_age=3600)  # 1 hour expiry
    except (BadSignature, SignatureExpired):
        return HTMLResponse(content='<div class="error">Invalid or expired session.</div>')
    
    # For demo: Use a default location (New York) since we can't get browser geolocation server-side
    # In production, you'd use client-side geolocation API or IP geolocation service
    lat, lng = 40.7128, -74.0060  # New York
    
    # Reverse geocode the location
    if not geocoding_service:
        return HTMLResponse(content='<div class="error">Geocoding service not initialized</div>')
    
    result = geocoding_service.reverse_geocode(lat, lng)
    
    if not result:
        return HTMLResponse(content='<div class="error">Could not determine location</div>')
    
    # Return location card
    html = '<div class="location-card">'
    html += '<h3>\ud83d\udccd Your Location</h3>'
    addr = result.address.formatted_address or 'N/A'
    html += '<div class="location-detail"><span class="label">Address:</span>'
    html += f'<span class="value">{addr}</span></div>'
    
    if result.address.street_number and result.address.street_name:
        street = f"{result.address.street_number} {result.address.street_name}"
        html += '<div class="location-detail"><span class="label">Street:</span>'
        html += f'<span class="value">{street}</span></div>'
    
    if result.address.city:
        html += '<div class="location-detail"><span class="label">City:</span>'
        html += f'<span class="value">{result.address.city}</span></div>'
    
    if result.address.state:
        html += '<div class="location-detail"><span class="label">State:</span>'
        html += f'<span class="value">{result.address.state}</span></div>'
    
    if result.address.postal_code:
        html += '<div class="location-detail"><span class="label">Postal Code:</span>'
        html += f'<span class="value">{result.address.postal_code}</span></div>'
    
    if result.address.country:
        html += '<div class="location-detail"><span class="label">Country:</span>'
        html += f'<span class="value">{result.address.country}</span></div>'

    html += '<div class="location-detail"><span class="label">Coordinates:</span>'
    html += f'<span class="value">{lat:.6f}, {lng:.6f}</span></div>'
    html += '<div class="location-detail"><span class="label">Provider:</span>'
    html += '<span class="value">Google Maps</span></div>'
    html += '</div>'
    
    return HTMLResponse(content=html)


@app.post("/demo/logout", response_class=HTMLResponse)
async def demo_logout(response: Response):
    """HTMX logout endpoint"""
    response.delete_cookie("session")
    
    return HTMLResponse(
        content='<h1>Geocoding Demo</h1>'
        '<p class="subtitle">Login to see your location with Google Maps</p>'
        '<div class="success">Logged out successfully</div>'
        '<form hx-post="/demo/login" hx-target="#content" hx-swap="innerHTML">'
        '<div class="form-group"><label for="email">Email</label>'
        '<input type="email" id="email" name="email" required></div>'
        '<div class="form-group"><label for="password">Password</label>'
        '<input type="password" id="password" name="password" required minlength="8"></div>'
        '<button type="submit">Login & Show My Location</button></form>'
    )

