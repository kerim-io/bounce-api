# Token Refresh Guide - BitBasel iOS Integration

## Token Expiration

**Access Token:** 30 minutes
**Refresh Token:** 7 days

## How It Works

1. After Apple Sign In, backend returns:
```json
{
  "access_token": "eyJhbGc...",       // Expires in 30 min
  "refresh_token": "eyJhbGc...",      // Expires in 7 days
  "token_type": "bearer",
  "user_id": 123,
  "email": "user@example.com",
  "has_profile": true
}
```

2. iOS should **store both tokens securely** (Keychain)

3. Use `access_token` for all API requests:
```
Authorization: Bearer {access_token}
```

4. When you get **401 Unauthorized**, refresh the token:

## Refresh Token Endpoint

**POST /auth/refresh**

### Request
```json
{
  "refresh_token": "eyJhbGc..."
}
```

### Response (Success)
```json
{
  "access_token": "eyJhbGc...",       // NEW access token
  "refresh_token": "eyJhbGc...",      // SAME refresh token
  "token_type": "bearer",
  "user_id": 123,
  "email": "user@example.com",
  "has_profile": true
}
```

### Response (Expired Refresh Token)
```json
{
  "detail": "Invalid or expired refresh token"
}
// Status: 401
// Action: Force user to sign in with Apple again
```

## iOS Implementation Pattern

### 1. Store Tokens After Sign In

```swift
struct AuthResponse: Codable {
    let accessToken: String
    let refreshToken: String?
    let tokenType: String
    let userId: Int
    let email: String?
    let hasProfile: Bool
}

class TokenManager {
    static let shared = TokenManager()

    func saveTokens(response: AuthResponse) {
        // Save to Keychain
        KeychainHelper.save(response.accessToken, for: "access_token")
        if let refreshToken = response.refreshToken {
            KeychainHelper.save(refreshToken, for: "refresh_token")
        }
    }

    func getAccessToken() -> String? {
        return KeychainHelper.load(for: "access_token")
    }

    func getRefreshToken() -> String? {
        return KeychainHelper.load(for: "refresh_token")
    }
}
```

### 2. API Request with Auto-Refresh

```swift
class APIClient {
    func request<T: Decodable>(
        _ endpoint: String,
        method: HTTPMethod = .get,
        body: Data? = nil
    ) async throws -> T {
        var request = URLRequest(url: URL(string: "\(baseURL)\(endpoint)")!)
        request.httpMethod = method.rawValue
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        // Add access token
        if let token = TokenManager.shared.getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // Handle 401 - Token Expired
        if httpResponse.statusCode == 401 {
            // Try to refresh token
            if try await refreshToken() {
                // Retry original request with new token
                return try await self.request(endpoint, method: method, body: body)
            } else {
                // Refresh failed - force re-login
                throw APIError.authenticationRequired
            }
        }

        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(httpResponse.statusCode)
        }

        return try JSONDecoder().decode(T.self, from: data)
    }

    @discardableResult
    func refreshToken() async throws -> Bool {
        guard let refreshToken = TokenManager.shared.getRefreshToken() else {
            return false
        }

        let url = URL(string: "\(baseURL)/auth/refresh")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["refresh_token": refreshToken]
        request.httpBody = try? JSONEncoder().encode(body)

        do {
            let (data, response) = try await URLSession.shared.data(for: request)

            guard let httpResponse = response as? HTTPURLResponse,
                  httpResponse.statusCode == 200 else {
                return false
            }

            let authResponse = try JSONDecoder().decode(AuthResponse.self, from: data)
            TokenManager.shared.saveTokens(response: authResponse)

            print("✅ Token refreshed successfully")
            return true

        } catch {
            print("❌ Token refresh failed: \(error)")
            return false
        }
    }
}
```

### 3. WebSocket Connection

**Important:** WebSocket also needs a valid token!

```swift
class FeedManager {
    func connect() {
        guard let token = TokenManager.shared.getAccessToken() else {
            print("No access token available")
            return
        }

        let urlString = "ws://localhost:8001/ws/feed?token=\(token)"
        guard let url = URL(string: urlString) else { return }

        webSocket = URLSession.shared.webSocketTask(with: url)
        webSocket?.resume()

        // Listen for messages
        receiveMessage()
    }

    func reconnectIfNeeded() async {
        // If WebSocket closes with 403 (expired token), refresh and reconnect
        if try await APIClient.shared.refreshToken() {
            connect()
        }
    }
}
```

### 4. Handle Token Expiry in App Lifecycle

```swift
@main
struct BitBaselApp: App {
    @Environment(\.scenePhase) var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
        .onChange(of: scenePhase) { oldPhase, newPhase in
            if newPhase == .active {
                // App became active - check token validity
                Task {
                    await checkAndRefreshToken()
                }
            }
        }
    }

    func checkAndRefreshToken() async {
        // Proactively refresh if token is close to expiring
        // (You can decode JWT to check exp claim)
        _ = try? await APIClient.shared.refreshToken()
    }
}
```

## Token Expiry Detection

You can decode the JWT to check expiry without calling the server:

```swift
import JWTDecode

extension TokenManager {
    func isAccessTokenExpired() -> Bool {
        guard let token = getAccessToken() else { return true }

        do {
            let jwt = try decode(jwt: token)

            // Check if expired (with 5 minute buffer)
            if let exp = jwt.expiresAt {
                return exp.timeIntervalSinceNow < 300 // 5 minutes
            }
        } catch {
            print("Failed to decode token: \(error)")
        }

        return true
    }

    func shouldRefreshToken() -> Bool {
        return isAccessTokenExpired()
    }
}
```

## Testing Token Refresh

### Test Expired Token
```bash
# 1. Get current token from iOS logs
TOKEN="your_access_token"

# 2. Wait 31 minutes (or use an old token)

# 3. Try to access protected endpoint
curl http://localhost:8001/posts/feed \
  -H "Authorization: Bearer $TOKEN"

# Expected: 401 Unauthorized

# 4. Refresh token
REFRESH_TOKEN="your_refresh_token"

curl -X POST http://localhost:8001/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"$REFRESH_TOKEN\"}" | python3 -m json.tool

# Expected: New access_token
```

## Best Practices

1. **Always store tokens in Keychain** (not UserDefaults)
2. **Refresh proactively** when app becomes active
3. **Retry failed requests** after token refresh
4. **Force re-login** if refresh token expires (after 7 days)
5. **Reconnect WebSocket** after token refresh
6. **Show loading state** during token refresh
7. **Log out user** if refresh fails repeatedly

## Error Scenarios

| Error | Status | Action |
|-------|--------|--------|
| Access token expired | 401 | Auto-refresh, retry request |
| Refresh token expired | 401 on /auth/refresh | Force Apple Sign In again |
| Network error during refresh | - | Retry with exponential backoff |
| Invalid token format | 401 | Clear tokens, force sign in |

## Security Notes

- **Never** log tokens to console in production
- **Never** send refresh_token in URL parameters
- **Always** use HTTPS in production (wss:// for WebSocket)
- **Clear** tokens on logout
- **Rotate** refresh token periodically (optional enhancement)

## Quick Checklist for iOS

- [ ] Save both access_token and refresh_token after sign in
- [ ] Add Authorization header to all API requests
- [ ] Handle 401 errors by calling /auth/refresh
- [ ] Retry original request after successful refresh
- [ ] Reconnect WebSocket after token refresh
- [ ] Force re-login if refresh token expires
- [ ] Test with expired tokens
