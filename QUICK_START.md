# Geocoding Quick Start Guide

## 🚀 Get Started in 3 Steps

### Step 1: Get Google Maps API Key
```bash
# 1. Visit: https://console.cloud.google.com/
# 2. Enable "Geocoding API"
# 3. Create API key
# 4. Update .env file:
nano .env
# Add: GOOGLE_MAPS_API_KEY=your-key-here
```

### Step 2: Install & Test
```bash
# Install dependencies
pip install -r requirements.txt

# Run test
python test_geocoding_integration.py

# Should see:
# ✓ Successfully imported geocoding service classes
# ✓ Valid coordinates created
# ✓ GeocodingService initialized successfully
```

### Step 3: Start Server & Use
```bash
# Start server
uvicorn main:app --reload

# Server will be at: http://localhost:8000
# API docs at: http://localhost:8000/docs
```

## 📍 API Endpoints (All Require Auth)

### Forward Geocoding (Address → Coordinates)
```bash
POST /geocoding/forward
GET  /geocoding/forward?address=...
```

**Example:**
```bash
curl -X POST http://localhost:8000/geocoding/forward \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"address": "Miami Beach Convention Center"}'
```

**Response:**
```json
{
  "coordinates": {"latitude": 25.790654, "longitude": -80.130045},
  "address": {
    "formatted_address": "1901 Convention Center Dr, Miami Beach, FL 33139",
    "city": "Miami Beach",
    "state": "FL",
    "country": "United States"
  }
}
```

### Reverse Geocoding (Coordinates → Address)
```bash
POST /geocoding/reverse
GET  /geocoding/reverse?lat=...&lon=...
```

**Example:**
```bash
curl -X GET "http://localhost:8000/geocoding/reverse?lat=25.7907&lon=-80.1300" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "address": {
    "formatted_address": "1901 Convention Center Dr, Miami Beach, FL 33139",
    "city": "Miami Beach",
    "state": "FL"
  },
  "coordinates": {"latitude": 25.7907, "longitude": -80.13}
}
```

## 🔑 Authentication

Same as all your other endpoints - use Apple Sign In access token:

```bash
# 1. Get token from Apple auth
POST /auth/apple
{
  "code": "APPLE_AUTH_CODE",
  "redirect_uri": "your-redirect-uri"
}

# Response includes: access_token

# 2. Use token for all requests
Authorization: Bearer {access_token}
```

## 📱 iOS Integration

```swift
// Same auth as rest of your app
let token = userSession.accessToken

// Forward geocoding
func searchLocation(query: String) async throws -> LocationResult {
    let url = URL(string: "\\(baseURL)/geocoding/forward")!
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")

    let body = ["address": query]
    request.httpBody = try JSONEncoder().encode(body)

    let (data, _) = try await URLSession.shared.data(for: request)
    return try JSONDecoder().decode(LocationResult.self, from: data)
}

// Reverse geocoding
func getAddress(lat: Double, lon: Double) async throws -> ReverseGeocodeResult {
    let url = URL(string: "\\(baseURL)/geocoding/reverse?lat=\\(lat)&lon=\\(lon)")!
    var request = URLRequest(url: url)
    request.setValue("Bearer \\(token)", forHTTPHeaderField: "Authorization")

    let (data, _) = try await URLSession.shared.data(for: request)
    return try JSONDecoder().decode(ReverseGeocodeResult.self, from: data)
}
```

## ✅ Verify It's Working

### Check 1: Server starts without errors
```bash
uvicorn main:app --reload
# Should see: Application startup complete
# Should NOT see: ModuleNotFoundError
```

### Check 2: Geocoding endpoints appear in docs
```bash
open http://localhost:8000/docs
# Scroll to "geocoding" section
# Should see 4 endpoints
```

### Check 3: Test with token
```bash
# Get token first
TOKEN=$(curl -X POST http://localhost:8000/auth/passcode \
  -H "Content-Type: application/json" \
  -d '{"passcode": "ARTBASEL2024"}' | jq -r .access_token)

# Test geocoding
curl -X POST http://localhost:8000/geocoding/forward \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"address": "Miami Beach"}'
```

## 🆘 Troubleshooting

### Error: "GOOGLE_MAPS_API_KEY not configured"
```bash
# Solution: Add API key to .env
echo 'GOOGLE_MAPS_API_KEY=your-key-here' >> .env
```

### Error: "ModuleNotFoundError: No module named 'geopy'"
```bash
# Solution: Install geopy
pip install geopy==2.4.1
# Or reinstall all
pip install -r requirements.txt
```

### Error: "Could not validate credentials"
```bash
# Solution: Check token
# 1. Get fresh token from /auth/apple or /auth/passcode
# 2. Include in header: Authorization: Bearer TOKEN
```

### Error: "Address not found"
```bash
# Solution: Be more specific
# ❌ Bad: "convention center"
# ✅ Good: "Miami Beach Convention Center, Miami Beach, FL"
```

## 💰 Pricing

**Google Maps Geocoding API:**
- Free tier: $200/month credit (~40,000 requests)
- Paid tier: $5 per 1,000 requests

**For Art Basel Miami:**
- Expected usage: 1,000-5,000 requests
- **Should stay in free tier**

## 📚 More Info

- `INTEGRATION_SUMMARY.md` - What was changed
- `GEOCODING_INTEGRATION.md` - Detailed guide
- `GEOCODING_ENHANCEMENTS.md` - Feature ideas
- `test_geocoding_integration.py` - Test script

---

**You're all set!** 🎉 The geocoding service is integrated and ready to use.
