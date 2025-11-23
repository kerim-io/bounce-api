# BitBasel Media Server

C++ WebRTC media server for BitBasel real-time streaming. Ported from OnlyLangs classroom streaming architecture.

## Architecture

**SFU (Selective Forwarding Unit)** design for efficient 1-to-many streaming:
```
User Posts Media → C++ Media Server (SFU) → Followers Stream/View
```

## Quick Start

### Build (Already Done)
```bash
cd media_server_cpp/build
cmake ..
make
```

### Run
```bash
# From project root
./start_media_server.sh

# Or manually
cd media_server_cpp/build
./media_server
```

Server will start on **http://localhost:8082**

## HTTP API

### Health Check
```bash
GET /health
Response: {"status": "healthy", "service": "media_server"}
```

### Create Room
```bash
POST /room/create
Body: {"post_id": "post_123", "host_user_id": "user_456"}
Response: {"room_id": "room_123456", "post_id": "post_123"}
```

### Stop Room
```bash
POST /room/{room_id}/stop
Response: {"status": "stopped", "room_id": "room_123456"}
```

### Room Statistics
```bash
GET /room/{room_id}/stats
Response: {
  "room_id": "room_123456",
  "post_id": "post_123",
  "is_active": true,
  "viewer_count": 25,
  "has_host": true
}
```

### Server Statistics
```bash
GET /stats
Response: {
  "total_rooms": 5,
  "active_rooms": 3,
  "total_peers": 78,
  "total_viewers": 75,
  "total_hosts": 3,
  "total_bytes_sent": 1234567890,
  "total_bytes_received": 987654321
}
```

## Python Integration

The FastAPI backend connects via `services/media_server_client.py`:

```python
from services.media_server_client import get_media_server_client

# Create room when user posts video/photo
media_client = get_media_server_client()
room_id = await media_client.create_room(str(post_id), str(user_id))

# Stop room when post is deleted
await media_client.stop_room(room_id)

# Get statistics
stats = await media_client.get_room_stats(room_id)
```

## Configuration

Edit `media_server_cpp/config.json`:

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8082,
    "max_connections": 1000
  },
  "rooms": {
    "max_rooms": 100,
    "max_viewers_per_room": 100,
    "idle_timeout_seconds": 300
  },
  "video": {
    "codec": "VP8",
    "target_bitrate_kbps": 1500,
    "max_framerate": 30
  },
  "audio": {
    "codec": "Opus",
    "bitrate_kbps": 128,
    "sample_rate": 48000
  }
}
```

## WebRTC Features

- **Video Codec:** VP8 (1500 kbps)
- **Audio Codec:** Opus (128 kbps, 48kHz)
- **ICE:** STUN server (Google public STUN)
- **Transport:** RTP/RTCP over UDP
- **Auto-cleanup:** Idle rooms removed after 5 minutes

## Development Status

✅ **Implemented:**
- HTTP REST API
- Room lifecycle management
- Statistics tracking
- Thread-safe operations
- Auto-cleanup

⚠️ **Simplified (Prototype):**
- WebRTC implementation (manual SDP generation)
- No actual media forwarding yet
- No WebSocket signaling

❌ **Needs for Production:**
- Full libwebrtc integration
- WebSocket for real-time signaling
- TLS/DTLS encryption
- Authentication tokens

## Testing

```bash
# Health check
curl http://localhost:8082/health

# Create room
curl -X POST http://localhost:8082/room/create \
  -H "Content-Type: application/json" \
  -d '{"post_id":"post_123","host_user_id":"user_456"}'

# Get stats
curl http://localhost:8082/stats
```

## Running Both Servers

```bash
# Terminal 1: FastAPI backend
uvicorn main:app --reload --port 8001

# Terminal 2: C++ media server
./start_media_server.sh
```

## Dependencies

- CMake >= 3.15
- C++17 compiler
- Boost (system, thread)
- pthread
- nlohmann/json (included)

## Port Configuration

- **FastAPI Backend:** 8001
- **C++ Media Server:** 8082
- **PostgreSQL:** 5432

## File Structure

```
media_server_cpp/
├── build/              # Compiled binary (333KB)
│   ├── media_server    # Executable
│   └── config.json     # Runtime config
├── src/                # C++ source files
│   ├── main.cpp
│   ├── streaming_server.cpp
│   ├── webrtc_handler.cpp
│   ├── room_manager.cpp
│   ├── http_server.cpp
│   └── config.cpp
├── include/            # Header files
│   ├── streaming_server.h
│   ├── webrtc_handler.h
│   ├── room_manager.h
│   ├── http_server.h
│   ├── config.h
│   └── json.hpp
├── CMakeLists.txt      # Build configuration
└── config.json         # Server configuration
```

## Notes

- Server now uses "post_id" field for BitBasel (accepts "classroom_id" for backwards compatibility)
- Thread-per-request model (simple but may need optimization for scale)
- No persistent storage (all state in-memory)
- Auto-cleanup runs every 30 seconds

## For Art Basel Launch

Current implementation is sufficient for MVP streaming features. Full production deployment would require WebRTC stack integration and WebSocket signaling.
