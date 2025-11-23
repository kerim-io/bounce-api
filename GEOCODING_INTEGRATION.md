# Geocoding Service Integration Guide

This guide explains how the geocoding service has been integrated into your Art Basel backend.

## Overview

The geocoding service from `pydantic-llm-mixin` has been integrated to work seamlessly with your existing Apple Sign In authentication. Users authenticate once with Apple, then can use geocoding endpoints throughout their session.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

This will install `geopy==2.4.1` (required for geocoding).

### 2. Get Google Maps API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable **Geocoding API** and **Maps JavaScript API**
4. Create credentials (API Key)
5. Add the API key to your `.env` file:

```bash
GOOGLE_MAPS_API_KEY=your-actual-api-key-here
```

### 3. (Optional) Restrict API Key

For security, restrict your API key in Google Cloud Console:
- Application restrictions: HTTP referrers or IP addresses
- API restrictions: Only enable Geocoding API

## API Endpoints

All geocoding endpoints require authentication (Apple Sign In access token).

### Forward Geocoding (Address → Coordinates)

**POST /geocoding/forward**
```bash
curl -X POST http://localhost:8000/geocoding/forward \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"address": "Miami Beach Convention Center, Miami Beach, FL"}'
```

**GET /geocoding/forward?address=...**
```bash
curl -X GET "http://localhost:8000/geocoding/forward?address=Miami%20Beach%20Convention%20Center" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "coordinates": {
    "latitude": 25.790654,
    "longitude": -80.130045
  },
  "address": {
    "formatted_address": "1901 Convention Center Dr, Miami Beach, FL 33139, USA",
    "street_number": "1901",
    "street_name": "Convention Center Drive",
    "city": "Miami Beach",
    "state": "FL",
    "postal_code": "33139",
    "country": "United States",
    "country_code": "US"
  },
  "place_id": "ChIJ...",
  "location_type": "ROOFTOP",
  "provider": "google",
  "timestamp": "2025-11-23T10:30:00Z",
  "confidence": null
}
```

### Reverse Geocoding (Coordinates → Address)

**POST /geocoding/reverse**
```bash
curl -X POST http://localhost:8000/geocoding/reverse \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 25.7907, "longitude": -80.1300}'
```

**GET /geocoding/reverse?lat=...&lon=...**
```bash
curl -X GET "http://localhost:8000/geocoding/reverse?lat=25.7907&lon=-80.1300" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

**Response:**
```json
{
  "address": {
    "formatted_address": "1901 Convention Center Dr, Miami Beach, FL 33139, USA",
    "street_number": "1901",
    "street_name": "Convention Center Drive",
    "city": "Miami Beach",
    "state": "FL",
    "postal_code": "33139",
    "country": "United States",
    "country_code": "US"
  },
  "coordinates": {
    "latitude": 25.7907,
    "longitude": -80.13
  },
  "provider": "google",
  "timestamp": "2025-11-23T10:30:00Z"
}
```

## Integration with Existing Features

### Location Updates (Geofence)

Your existing `/users/me/location` endpoint updates user location and checks Art Basel geofence. You can now enhance it with geocoding:

```python
# In api/routes/users.py
from services.geocoding import GeocodingService

@router.post("/me/location", response_model=LocationResponse)
async def update_location(
    location: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    # Existing geofence logic...

    # Optional: Add reverse geocoding to get address
    if settings.GOOGLE_MAPS_API_KEY:
        service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
        geo_result = service.reverse_geocode(location.latitude, location.longitude)
        if geo_result:
            # Store address in user profile or return in response
            print(f"User at: {geo_result.address.formatted_address}")

    return LocationResponse(...)
```

### Check-Ins with Address

Enhance check-ins with human-readable addresses:

```python
# In api/routes/checkins.py
@router.post("/", response_model=CheckInResponse)
async def create_checkin(
    checkin_data: CheckInCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    # Get address from coordinates
    if settings.GOOGLE_MAPS_API_KEY:
        service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
        geo_result = service.reverse_geocode(
            checkin_data.latitude,
            checkin_data.longitude
        )
        location_name = geo_result.address.formatted_address if geo_result else None

    checkin = CheckIn(
        user_id=current_user.id,
        latitude=checkin_data.latitude,
        longitude=checkin_data.longitude,
        location_name=location_name  # Now has real address!
    )
    # ...
```

## Authentication Flow

1. **User signs in with Apple** → Receives `access_token`
2. **User makes geocoding request** → Includes `Authorization: Bearer {access_token}` header
3. **Backend validates token** → Uses existing `get_current_user` dependency
4. **Geocoding service called** → Returns results

## Error Handling

- **401 Unauthorized**: Missing or invalid access token (Apple auth required)
- **404 Not Found**: Address/location not found by Google Maps
- **503 Service Unavailable**: Google Maps API key not configured

## Cost Considerations

Google Maps Geocoding API pricing (as of 2024):
- **Free tier**: $200 credit per month (~40,000 requests)
- **Paid tier**: $5 per 1,000 requests after free tier

For Art Basel Miami app:
- Estimated usage: ~1,000-5,000 geocoding requests during event
- **Likely stays within free tier**

## Testing

### 1. Get Access Token
```bash
# Sign in with Apple first
curl -X POST http://localhost:8000/auth/apple \
  -H "Content-Type: application/json" \
  -d '{"code": "APPLE_AUTH_CODE", "redirect_uri": "your-redirect-uri"}'

# Response includes access_token
```

### 2. Test Forward Geocoding
```bash
export TOKEN="your_access_token_here"

curl -X POST http://localhost:8000/geocoding/forward \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"address": "Art Basel Miami Beach"}'
```

### 3. Test Reverse Geocoding
```bash
curl -X POST http://localhost:8000/geocoding/reverse \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"latitude": 25.7907, "longitude": -80.1300}'
```

## File Structure

```
bit_basel_backend/
├── services/
│   └── geocoding/
│       ├── __init__.py      # Package exports
│       ├── models.py        # Pydantic models (Coordinates, Address, etc.)
│       └── service.py       # GeocodingService class
├── api/
│   └── routes/
│       └── geocoding.py     # Geocoding endpoints
├── core/
│   └── config.py            # Added GOOGLE_MAPS_API_KEY setting
├── .env                     # Added GOOGLE_MAPS_API_KEY
├── requirements.txt         # Added geopy==2.4.1
└── main.py                  # Added geocoding router
```

## Next Steps

1. **Get Google Maps API Key** and add to `.env`
2. **Test endpoints** with your Apple Sign In tokens
3. **Integrate with check-ins** for better location names
4. **Add to iOS app** for address search/autocomplete
5. **Monitor API usage** in Google Cloud Console

## Support

If you encounter issues:
- Check that `GOOGLE_MAPS_API_KEY` is set in `.env`
- Verify API key has Geocoding API enabled
- Check API key restrictions (IP/referrer)
- Review Google Cloud Console quota/billing
