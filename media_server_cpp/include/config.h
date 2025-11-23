#ifndef CONFIG_H
#define CONFIG_H

#include <string>
#include <vector>
#include <fstream>
#include <iostream>

namespace onlylang {

struct IceServer {
    std::vector<std::string> urls;
};

struct ServerConfig {
    std::string host = "0.0.0.0";
    int port = 8080;
    int max_connections = 1000;
};

struct WebRTCConfig {
    std::vector<IceServer> ice_servers;
    bool enable_dtls = true;
    bool enable_rtp_rtcp_mux = true;
};

struct RoomConfig {
    int max_rooms = 100;
    int max_viewers_per_room = 100;
    int idle_timeout_seconds = 300;
};

struct VideoConfig {
    std::string codec = "VP8";
    int max_bitrate_kbps = 2500;
    int min_bitrate_kbps = 500;
    int target_bitrate_kbps = 1500;
    int max_framerate = 30;
};

struct AudioConfig {
    std::string codec = "Opus";
    int bitrate_kbps = 128;
    int sample_rate = 48000;
};

struct LoggingConfig {
    std::string level = "info";
    std::string file = "media_server.log";
    bool console = true;
};

class Config {
public:
    ServerConfig server;
    WebRTCConfig webrtc;
    RoomConfig rooms;
    VideoConfig video;
    AudioConfig audio;
    LoggingConfig logging;

    // Load configuration from JSON file
    bool load(const std::string& filename);

    // Get singleton instance
    static Config& instance() {
        static Config instance;
        return instance;
    }

private:
    Config() = default;
};

} // namespace onlylang

#endif // CONFIG_H