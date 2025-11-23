# Geocoding Enhancement Ideas

Here are some ways to enhance your existing backend with geocoding:

## 1. Enhanced Location Updates with Address

Enhance `/users/me/location` to return the address where user is located:

```python
# In api/routes/users.py

from services.geocoding import GeocodingService
from typing import Optional

class LocationResponse(BaseModel):
    can_post: bool
    message: str
    distance_km: Optional[float] = None
    address: Optional[str] = None  # NEW: Add address
    city: Optional[str] = None      # NEW: Add city

@router.post("/me/location", response_model=LocationResponse)
async def update_location(
    location: LocationUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    # ... existing geofence logic ...

    # Add reverse geocoding
    address_str = None
    city = None
    if settings.GOOGLE_MAPS_API_KEY:
        try:
            service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
            geo_result = service.reverse_geocode(location.latitude, location.longitude)
            if geo_result:
                address_str = geo_result.address.formatted_address
                city = geo_result.address.city
        except Exception as e:
            print(f"Geocoding error: {e}")

    if can_post:
        return LocationResponse(
            can_post=True,
            message=f"Welcome to Art Basel Miami! You can now post and like.",
            distance_km=round(distance_km, 2),
            address=address_str,
            city=city
        )
    else:
        return LocationResponse(
            can_post=False,
            message=f"You're {round(distance_km, 2)} km from Art Basel Miami.",
            distance_km=round(distance_km, 2),
            address=address_str,
            city=city
        )
```

## 2. Smart Check-Ins with Automatic Location Names

Update `/checkins` to automatically populate location names:

```python
# In api/routes/checkins.py

@router.post("/", response_model=CheckInResponse)
async def create_checkin(
    checkin_data: CheckInCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    # Automatically get location name from coordinates
    location_name = checkin_data.location_name  # User-provided (optional)

    if not location_name and settings.GOOGLE_MAPS_API_KEY:
        try:
            service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
            geo_result = service.reverse_geocode(
                checkin_data.latitude,
                checkin_data.longitude
            )
            if geo_result:
                # Use venue name or formatted address
                location_name = geo_result.address.formatted_address
        except Exception as e:
            print(f"Geocoding error: {e}")

    checkin = CheckIn(
        user_id=current_user.id,
        latitude=checkin_data.latitude,
        longitude=checkin_data.longitude,
        location_name=location_name
    )

    # ... rest of endpoint ...
```

## 3. Venue Search Endpoint

Add a new endpoint for searching Art Basel venues by name:

```python
# In api/routes/geocoding.py

@router.get("/search/venues", response_model=List[LocationResult])
async def search_venues(
    query: str = Query(..., description="Venue name or address", min_length=2),
    current_user: User = Depends(get_current_user)
):
    """
    Search for Art Basel venues near Miami Beach

    Example: /geocoding/search/venues?query=art+basel
    """
    service = get_geocoding_service()

    # Add "Miami Beach" to query for better results
    full_query = f"{query}, Miami Beach, FL"

    result = service.geocode(full_query)

    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")

    return [result]
```

## 4. Distance Calculator Between Users

Add endpoint to calculate distance between current user and another user:

```python
# In api/routes/users.py

class UserDistanceResponse(BaseModel):
    user_id: int
    nickname: Optional[str]
    distance_km: float
    can_see_location: bool

@router.get("/{user_id}/distance", response_model=UserDistanceResponse)
async def get_distance_to_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Calculate distance between current user and another user.
    Only works if both users are geolocated at Art Basel (can_post=True).
    """
    # Get target user
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()

    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if both users have location
    if not (current_user.last_location_lat and target_user.last_location_lat):
        raise HTTPException(
            status_code=400,
            detail="Location data not available for one or both users"
        )

    # Calculate distance
    distance = haversine_distance(
        current_user.last_location_lat,
        current_user.last_location_lon,
        target_user.last_location_lat,
        target_user.last_location_lon
    )

    return UserDistanceResponse(
        user_id=target_user.id,
        nickname=target_user.nickname,
        distance_km=round(distance, 2),
        can_see_location=target_user.can_post
    )
```

## 5. Nearby Users Finder

Find users within a certain radius:

```python
# In api/routes/users.py

class NearbyUsersRequest(BaseModel):
    radius_km: float = Field(default=1.0, ge=0.1, le=10)

class NearbyUserResponse(BaseModel):
    id: int
    nickname: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    profile_picture: Optional[str]
    distance_km: float

@router.post("/nearby", response_model=List[NearbyUserResponse])
async def find_nearby_users(
    request: NearbyUsersRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Find users within specified radius (default 1km).
    Only shows users who are at Art Basel (can_post=True).
    """
    if not (current_user.last_location_lat and current_user.last_location_lon):
        raise HTTPException(
            status_code=400,
            detail="Your location is not available. Update location first."
        )

    # Get all users with location who can post
    result = await db.execute(
        select(User).where(
            User.can_post == True,
            User.id != current_user.id,
            User.last_location_lat.isnot(None)
        )
    )
    users = result.scalars().all()

    # Calculate distances and filter
    nearby_users = []
    for user in users:
        distance = haversine_distance(
            current_user.last_location_lat,
            current_user.last_location_lon,
            user.last_location_lat,
            user.last_location_lon
        )

        if distance <= request.radius_km:
            nearby_users.append(NearbyUserResponse(
                id=user.id,
                nickname=user.nickname,
                first_name=user.first_name,
                last_name=user.last_name,
                profile_picture=user.profile_picture,
                distance_km=round(distance, 2)
            ))

    # Sort by distance
    nearby_users.sort(key=lambda x: x.distance_km)

    return nearby_users
```

## 6. Post Location Enrichment

Show better location info on posts:

```python
# In api/routes/posts.py

class PostResponse(BaseModel):
    id: int
    content: str
    media_url: Optional[str]
    media_type: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    location_name: Optional[str]  # NEW: Add location name
    city: Optional[str]            # NEW: Add city
    created_at: datetime
    user: SimpleUserResponse
    likes_count: int
    is_liked: bool

# When creating posts, optionally geocode the location
@router.post("/", response_model=PostResponse)
async def create_post(
    post_data: PostCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    # ... existing validation ...

    # Optionally reverse geocode post location
    location_name = None
    city = None
    if post_data.latitude and post_data.longitude and settings.GOOGLE_MAPS_API_KEY:
        try:
            service = GeocodingService(google_api_key=settings.GOOGLE_MAPS_API_KEY)
            geo_result = service.reverse_geocode(
                post_data.latitude,
                post_data.longitude
            )
            if geo_result:
                location_name = geo_result.address.formatted_address
                city = geo_result.address.city
        except Exception as e:
            print(f"Geocoding error: {e}")

    # Store location_name in post (requires DB migration to add field)
    # For now, just return it in response

    # ... rest of endpoint ...
```

## 7. iOS App Integration Examples

### Forward Geocoding (Address Search)
```swift
// Search for venues
func searchVenue(query: String) async throws -> LocationResult {
    let url = URL(string: "\\(baseURL)/geocoding/forward")!
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("Bearer \\(accessToken)", forHTTPHeaderField: "Authorization")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")

    let body = ["address": query]
    request.httpBody = try JSONEncoder().encode(body)

    let (data, _) = try await URLSession.shared.data(for: request)
    return try JSONDecoder().decode(LocationResult.self, from: data)
}
```

### Reverse Geocoding (Get Address from GPS)
```swift
// Get address from user's GPS coordinates
func getAddressFromLocation(latitude: Double, longitude: Double) async throws -> ReverseGeocodeResult {
    let url = URL(string: "\\(baseURL)/geocoding/reverse?lat=\\(latitude)&lon=\\(longitude)")!
    var request = URLRequest(url: url)
    request.setValue("Bearer \\(accessToken)", forHTTPHeaderField: "Authorization")

    let (data, _) = try await URLSession.shared.data(for: request)
    return try JSONDecoder().decode(ReverseGeocodeResult.self, from: data)
}
```

### Enhanced Location Update
```swift
// Update location with address info
func updateLocation(latitude: Double, longitude: Double) async throws -> LocationResponse {
    let url = URL(string: "\\(baseURL)/users/me/location")!
    var request = URLRequest(url: url)
    request.httpMethod = "POST"
    request.setValue("Bearer \\(accessToken)", forHTTPHeaderField: "Authorization")
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")

    let body = ["latitude": latitude, "longitude": longitude]
    request.httpBody = try JSONEncoder().encode(body)

    let (data, _) = try await URLSession.shared.data(for: request)
    let response = try JSONDecoder().decode(LocationResponse.self, from: data)

    // Now response includes address and city!
    print("You're at: \\(response.address ?? "unknown")")
    print("City: \\(response.city ?? "unknown")")

    return response
}
```

## Summary

The geocoding service integrates seamlessly with your Apple auth system:

1. **No changes to auth flow** - Users still sign in with Apple
2. **Same access tokens** - Geocoding endpoints use existing JWT tokens
3. **Drop-in enhancement** - Add geocoding to existing endpoints without breaking changes
4. **Optional feature** - Works even if GOOGLE_MAPS_API_KEY is not set (graceful degradation)

Pick the enhancements that make sense for your app and implement them incrementally!
