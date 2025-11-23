# Embeddable Map Widgets Guide

Serve interactive Google Maps widgets that other systems can embed via iframe.

## Features

- **Interactive Search**: Users can search for addresses with autocomplete
- **Click to Geocode**: Click anywhere on the map to reverse geocode
- **Customizable**: Set default location, zoom level, and dimensions
- **Authenticated**: Optional JWT token for secure API calls
- **Responsive**: Works on desktop and mobile devices
- **Easy Embedding**: Simple iframe code for any website

## Quick Start

### 1. Get Your API Keys

You need **TWO** separate Google Maps API keys:

1. **Backend API Key** (`GOOGLE_MAPS_API_KEY` env var)
   - Used by your server for geocoding API calls
   - Restrict to: Geocoding API, Places API
   - Restrict to: Server IP addresses

2. **JavaScript API Key** (for widget embedding)
   - Used by the widget in the user's browser
   - Restrict to: Maps JavaScript API, Places API
   - Restrict to: HTTP referrers (your domain + embedded domains)

### 2. Enable Required APIs

In Google Cloud Console, enable:
- **Geocoding API** (for backend)
- **Places API** (for both backend and frontend)
- **Maps JavaScript API** (for frontend widget)

### 3. Start Your Server

```bash
GOOGLE_MAPS_API_KEY="your-backend-key" \
APPROVED_USERS="user@example.com" \
JWT_SECRET_KEY="your-secret" \
uv run uvicorn examples.geocoding_api:app --host 0.0.0.0 --port 8200
```

## Embedding the Widget

### Option 1: Direct Iframe (Simplest)

```html
<iframe
    src="https://your-domain.com/widgets/map?api_key=YOUR_JS_API_KEY"
    width="100%"
    height="600px"
    frameborder="0"
    style="border:0"
    allowfullscreen>
</iframe>
```

### Option 2: Get Embed Code from API

```bash
curl "https://your-domain.com/widgets/embed-code?api_key=YOUR_JS_API_KEY&width=100%&height=600px"
```

**Response:**
```json
{
    "iframe": "<iframe src='...' width='100%' height='600px'></iframe>",
    "widget_url": "/widgets/map?api_key=...",
    "instructions": "Copy the iframe code and paste it into your HTML"
}
```

### Option 3: Customized Widget

```html
<iframe
    src="https://your-domain.com/widgets/map?api_key=YOUR_JS_API_KEY&lat=37.7749&lng=-122.4194&zoom=12"
    width="800px"
    height="500px"
    frameborder="0"
    style="border:0"
    allowfullscreen>
</iframe>
```

## Widget Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `api_key` | ✅ Yes | - | Your Google Maps JavaScript API key |
| `token` | No | - | JWT token for authenticated API calls |
| `lat` | No | 40.7128 | Initial map latitude (New York) |
| `lng` | No | -74.0060 | Initial map longitude (New York) |
| `zoom` | No | 13 | Initial zoom level (1-20) |

## Authentication

### Public Widget (No Auth)

For public-facing widgets where anyone can search:

```html
<iframe src="https://your-domain.com/widgets/map?api_key=YOUR_JS_API_KEY"></iframe>
```

**Note:** Backend geocoding calls will fail without JWT token, but widget will still show the map.

### Authenticated Widget

For widgets that need backend geocoding:

1. Get JWT token from `/auth/login`
2. Pass token to widget:

```html
<iframe src="https://your-domain.com/widgets/map?api_key=YOUR_JS_API_KEY&token=YOUR_JWT_TOKEN"></iframe>
```

## Use Cases

### 1. Embed in Documentation

```markdown
# Our Locations

<iframe src="https://geocoding.yourcompany.com/widgets/map?api_key=YOUR_KEY&lat=37.7749&lng=-122.4194" width="100%" height="400"></iframe>
```

### 2. Customer Dashboard

```html
<!-- In customer portal -->
<div class="map-container">
    <iframe
        src="https://api.yourcompany.com/widgets/map?api_key=YOUR_KEY&token={{ user.jwt_token }}"
        width="100%"
        height="600px"
        style="border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
    </iframe>
</div>
```

### 3. Mobile App WebView

```swift
// iOS WebView
let url = URL(string: "https://api.yourcompany.com/widgets/map?api_key=\(apiKey)&token=\(authToken)")
webView.load(URLRequest(url: url!))
```

### 4. Third-Party Integration

Allow partners to embed your geocoding map on their sites:

```html
<!-- Partner's website -->
<iframe
    src="https://geocoding-api.yourcompany.com/widgets/map?api_key=PARTNER_KEY&lat=40.7128&lng=-74.0060"
    width="100%"
    height="500px">
</iframe>
```

## Widget Features

### Search with Autocomplete
- Type in the search box to find addresses
- Powered by Google Places Autocomplete
- Click on suggestion to center map

### Click to Reverse Geocode
- Click anywhere on the map
- Displays detailed address information
- Shows coordinates

### Info Windows
Clicking a location shows:
- Full formatted address
- Street number and name
- City, state, postal code
- Country
- Exact coordinates

## Security Best Practices

### API Key Restrictions

**JavaScript API Key** (for widgets):
```
Application restrictions:
- HTTP referrers: https://yourcompany.com/*, https://partner.com/*

API restrictions:
- Maps JavaScript API
- Places API
```

**Backend API Key** (server-only):
```
Application restrictions:
- IP addresses: YOUR_SERVER_IP

API restrictions:
- Geocoding API
- Places API
```

### JWT Token Security

1. **Short expiration**: Tokens expire in 30 minutes
2. **HTTPS only**: Never embed widgets over HTTP
3. **Approved users**: Only whitelisted emails can get tokens
4. **Regenerate**: Users can get fresh tokens via `/auth/login`

## Responsive Design

The widget automatically adapts to container size:

```html
<!-- Mobile-friendly -->
<div style="width: 100%; max-width: 600px; margin: 0 auto;">
    <iframe
        src="https://your-domain.com/widgets/map?api_key=YOUR_KEY"
        width="100%"
        height="400px"
        style="border: none; border-radius: 8px;">
    </iframe>
</div>
```

## Troubleshooting

### Widget shows blank page
- Check that JavaScript API key is valid
- Verify API key restrictions allow your domain
- Check browser console for errors

### "This page can't load Google Maps correctly"
- JavaScript API key is missing or invalid
- Maps JavaScript API not enabled in Google Cloud Console
- API key restrictions are blocking the domain

### Geocoding doesn't work
- Backend API key (`GOOGLE_MAPS_API_KEY`) not set
- JWT token expired or invalid
- User email not in `APPROVED_USERS` list

### CORS errors
- Ensure widget is loaded via HTTPS
- Check that backend allows the origin domain

## Cost Optimization

### Stay Within Free Tier

Google Maps provides **$200/month free tier**:
- **Maps JavaScript API**: $7 per 1,000 loads
- **Geocoding API**: $5 per 1,000 requests
- **Places API**: $17 per 1,000 requests (autocomplete)

**Tips to minimize costs:**

1. **Cache geocoding results** on your backend
2. **Limit autocomplete** to specific regions
3. **Use session tokens** for autocomplete
4. **Set up billing alerts** in Google Cloud Console
5. **Monitor usage** regularly

### Example Cost Calculation

With 10,000 monthly widget views:
- Widget loads: 10,000 × $7/1000 = $70
- Geocoding calls: 5,000 × $5/1000 = $25
- Autocomplete: 3,000 × $17/1000 = $51
- **Total: $146/month** (within $200 free tier)

## Production Deployment

### Railway Example

```bash
# Set environment variables
railway variables set GOOGLE_MAPS_API_KEY="your-backend-key"
railway variables set APPROVED_USERS="user1@example.com,user2@example.com"
railway variables set JWT_SECRET_KEY="$(openssl rand -base64 32)"

# Deploy
railway up
```

### Embed on Production

```html
<iframe
    src="https://your-railway-app.railway.app/widgets/map?api_key=YOUR_JS_KEY"
    width="100%"
    height="600px">
</iframe>
```

## Advanced Customization

### Custom Styling

Wrap the iframe with custom CSS:

```html
<div class="geocoding-widget">
    <h2>Find a Location</h2>
    <iframe
        src="https://your-domain.com/widgets/map?api_key=YOUR_KEY"
        width="100%"
        height="500px">
    </iframe>
</div>

<style>
.geocoding-widget {
    max-width: 1200px;
    margin: 40px auto;
    padding: 20px;
    background: white;
    border-radius: 12px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12);
}

.geocoding-widget h2 {
    margin-bottom: 20px;
    color: #333;
}

.geocoding-widget iframe {
    border-radius: 8px;
}
</style>
```

### Multiple Widgets on One Page

```html
<!-- New York Office -->
<iframe
    src="https://your-domain.com/widgets/map?api_key=YOUR_KEY&lat=40.7128&lng=-74.0060&zoom=15"
    width="48%"
    height="400px">
</iframe>

<!-- San Francisco Office -->
<iframe
    src="https://your-domain.com/widgets/map?api_key=YOUR_KEY&lat=37.7749&lng=-122.4194&zoom=15"
    width="48%"
    height="400px">
</iframe>
```

## Support

For issues or questions:
1. Check the [main documentation](GEOCODING_README.md)
2. Verify your API keys and restrictions
3. Check browser console for errors
4. Review Google Cloud Console for quota/billing issues
