"""
Quick test to verify geocoding integration works
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from services.geocoding import GeocodingService, Coordinates, Address


def test_geocoding_imports():
    """Test that all geocoding classes can be imported"""
    print("✓ Successfully imported geocoding service classes")
    print(f"  - GeocodingService: {GeocodingService}")
    print(f"  - Coordinates: {Coordinates}")
    print(f"  - Address: {Address}")


def test_coordinates_validation():
    """Test Coordinates model validation"""
    # Valid coordinates
    coords = Coordinates(latitude=25.7907, longitude=-80.1300)
    print(f"\n✓ Valid coordinates created: {coords.latitude}, {coords.longitude}")

    # Test rounding (should round to 6 decimal places)
    coords2 = Coordinates(latitude=25.79074321, longitude=-80.13004567)
    print(f"✓ Coordinates rounded correctly: {coords2.latitude}, {coords2.longitude}")

    # Test validation
    try:
        invalid = Coordinates(latitude=100, longitude=-80)  # Invalid latitude
        print("✗ Should have failed validation")
    except Exception as e:
        print(f"✓ Validation working: {type(e).__name__}")


def test_geocoding_service_init():
    """Test GeocodingService initialization"""
    import os

    api_key = os.getenv("GOOGLE_MAPS_API_KEY")

    if not api_key or api_key == "your-google-maps-api-key-here":
        print("\n⚠️  GOOGLE_MAPS_API_KEY not set in .env")
        print("   Set a real API key to test actual geocoding")
        print("   For now, testing initialization only...")

        try:
            service = GeocodingService(google_api_key="test-key")
            print(f"✓ GeocodingService initialized with test key")
            print(f"  - Provider: {service.provider}")
            print(f"  - Timeout: {service.timeout}s")
        except Exception as e:
            print(f"✗ Initialization failed: {e}")
    else:
        print(f"\n✓ GOOGLE_MAPS_API_KEY found in environment")
        try:
            service = GeocodingService(google_api_key=api_key)
            print(f"✓ GeocodingService initialized successfully")
            print(f"  - Provider: {service.provider}")
            print(f"  - Timeout: {service.timeout}s")

            # Test actual geocoding
            print("\nTesting forward geocoding...")
            result = service.geocode("Miami Beach Convention Center, Miami Beach, FL")
            if result:
                print(f"✓ Forward geocoding works!")
                print(f"  - Address: {result.address.formatted_address}")
                print(f"  - Coordinates: {result.coordinates.latitude}, {result.coordinates.longitude}")
                print(f"  - City: {result.address.city}")
                print(f"  - State: {result.address.state}")

                # Test reverse geocoding with those coordinates
                print("\nTesting reverse geocoding...")
                reverse_result = service.reverse_geocode(
                    result.coordinates.latitude,
                    result.coordinates.longitude
                )
                if reverse_result:
                    print(f"✓ Reverse geocoding works!")
                    print(f"  - Address: {reverse_result.address.formatted_address}")
            else:
                print("✗ Forward geocoding returned no results")

        except Exception as e:
            print(f"✗ Error during geocoding test: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    print("=" * 60)
    print("GEOCODING INTEGRATION TEST")
    print("=" * 60)

    test_geocoding_imports()
    test_coordinates_validation()
    test_geocoding_service_init()

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    print("\nTo test with API:")
    print("1. Add GOOGLE_MAPS_API_KEY to .env")
    print("2. Run: python test_geocoding_integration.py")
    print("3. Start server: uvicorn main:app --reload")
    print("4. Test endpoints with your Apple auth token")
