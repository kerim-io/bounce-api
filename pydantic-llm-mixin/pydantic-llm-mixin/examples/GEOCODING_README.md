# Geocoding API with Authentication

Production-ready geocoding service with JWT authentication and approved users whitelist.

## Features

- **Forward Geocoding**: Convert addresses to coordinates
- **Reverse Geocoding**: Convert coordinates to addresses
- **Google Maps API**: Production-grade geocoding with rich address data
- **JWT Authentication**: Secure token-based authentication
- **Approved Users Whitelist**: Email-based access control
- **Type-Safe**: Full Pydantic validation

## Authentication Flow

1. **User Login**: Client sends email + password to `/auth/login`
2. **Email Verification**: Server checks if email is in `APPROVED_USERS` list
3. **Password Validation**: Server validates password meets minimum requirements (8+ characters)
4. **Token Issuance**: Server generates JWT token (30-minute expiration)
5. **Client Storage**: Client stores token (CLI saves to `.jwt_token` file)
6. **API Requests**: Client includes token in `Authorization: Bearer <token>` header
7. **Token Validation**: Server verifies token signature and expiration on each request
8. **Authorization Check**: Server re-validates email is still in approved list

**Security Notes:**
- Tokens expire after 30 minutes - client must re-login
- Email must remain in `APPROVED_USERS` for token to remain valid
- For production: Replace demo password validation with database lookup + bcrypt hashing

## Environment Variables

### Required
- `APPROVED_USERS`: Comma-separated list of approved email addresses
  - Example: `"user1@example.com,user2@example.com,admin@company.com"`
  - **Important**: Only these emails can authenticate
- `GOOGLE_MAPS_API_KEY`: Google Maps API key (required)
  - See setup instructions below
- `JWT_SECRET_KEY`: Secret key for JWT tokens (use strong random value in production)

## Quick Start

### 1. Install Dependencies

```bash
uv add geopy email-validator
```

### 2. Set Up Google Maps API (Required)

Follow the steps in **Google Maps API Setup** section below to get your API key.

### 3. Run Locally

```bash
GOOGLE_MAPS_API_KEY="your-api-key" APPROVED_USERS="your@email.com" JWT_SECRET_KEY="your-secret-key" uv run uvicorn examples.geocoding_api:app --host 0.0.0.0 --port 8200
```

### 4. Test with CLI

```bash
# Login (you'll be prompted for email and password)
uv run python cli.py login

# Geocode an address
uv run python cli.py geocode "Statue of Liberty, New York"

# Reverse geocode coordinates
uv run python cli.py reverse 37.422408 -122.084068
```

## API Endpoints

### Authentication

#### POST /auth/login
Login to get JWT token.

**Request:**
```json
{
  "email": "test@example.com",
  "password": "your_password_here"
}
```

**Response:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer"
}
```

**Notes:**
- Email must be in the `APPROVED_USERS` list
- Password must be at least 8 characters
- In production, replace password validation with database lookup

#### GET /auth/me
Get current user info (requires authentication).

### Geocoding

#### GET /geocode?address=...
Convert address to coordinates (requires authentication).

**Example:**
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8200/geocode?address=Statue%20of%20Liberty,%20New%20York"
```

**Response:**
```json
{
  "coordinates": {
    "latitude": 40.689253,
    "longitude": -74.044548
  },
  "address": {
    "formatted_address": "Statue of Liberty, ...",
    ...
  },
  "provider": "nominatim",
  "timestamp": "2025-11-23T14:43:57Z"
}
```

#### GET /reverse?lat=...&lon=...
Convert coordinates to address (requires authentication).

**Example:**
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8200/reverse?lat=37.422408&lon=-122.084068"
```

**Response:**
```json
{
  "address": {
    "formatted_address": "Google Building 40, ...",
    "street_number": "40",
    "street_name": "Amphitheatre Parkway",
    "city": "Mountain View",
    "state": "California",
    "postal_code": "94043",
    "country": "United States of America",
    "country_code": "US"
  },
  "coordinates": {
    "latitude": 37.422408,
    "longitude": -122.084068
  },
  "provider": "nominatim"
}
```

## Google Maps API Setup (Required for Production)

### Step 1: Create Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click "Select a project" → "New Project"
3. Name your project (e.g., "geocoding-app")
4. Set up billing (required but includes **$200/month free tier**)

### Step 2: Enable Required APIs
1. Navigate to "APIs & Services" → "Library"
2. Search and enable these APIs:
   - **Geocoding API** (for address → coordinates)
   - **Places API** (for place lookups)
   - **Maps JavaScript API** (if using web interface)

### Step 3: Create API Key
1. Go to "APIs & Services" → "Credentials"
2. Click "+ CREATE CREDENTIALS" → "API key"
3. Copy the generated API key
4. Save it securely - you'll need it for the `GOOGLE_MAPS_API_KEY` environment variable

### Step 4: Restrict API Key (Recommended for Production)
1. Click "RESTRICT KEY" on the newly created key
2. Under **"API restrictions"**:
   - Select "Restrict key"
   - Choose: Geocoding API, Places API
3. Under **"Application restrictions"** (for production):
   - **HTTP referrers** for web apps
   - **IP addresses** for server-side apps (add your Railway/server IP)

**For Development**: Leave restrictions off or add your server IP
**For Production**: Always restrict to specific IPs or referrers

## Railway Deployment

### 1. Set Environment Variables in Railway

```bash
railway variables set APPROVED_USERS="user1@example.com,user2@example.com"
railway variables set JWT_SECRET_KEY="your-secret-key-here"
railway variables set GOOGLE_MAPS_API_KEY="your-google-api-key"
```

### 2. Deploy

```bash
railway up
```

## Security Notes

- Never commit API keys or JWT secrets to git
- Always use environment variables for sensitive data
- Set `APPROVED_USERS` to restrict access
- In production, implement proper password hashing and database authentication
- Restrict Google Maps API keys to specific IPs/domains in production

## Cost Considerations

### Google Maps Pricing
- **Free tier**: $200/month credit (~40,000 requests)
- **Cost after free tier**: $5 per 1,000 requests
- **Benefits**: Most accurate geocoding, rich data, global coverage

## Production Recommendations

1. **Implement caching** to reduce API calls and stay within free tier
2. **Add rate limiting** to prevent abuse
3. **Replace demo authentication** with proper user database and password hashing
4. **Monitor usage** in Google Cloud Console to track API costs
