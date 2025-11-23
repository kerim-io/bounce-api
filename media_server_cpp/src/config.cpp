#include "config.h"
#include "json.hpp"
#include <fstream>
#include <iostream>

using json = nlohmann::json;

namespace onlylang {

bool Config::load(const std::string& filename) {
    try {
        std::ifstream file(filename);
        if (!file.is_open()) {
            std::cerr << "Cannot open config file: " << filename << std::endl;
            return false;
        }

        json j;
        file >> j;

        // Parse server config
        if (j.contains("server")) {
            server.host = j["server"].value("host", "0.0.0.0");
            server.port = j["server"].value("port", 8080);
            server.max_connections = j["server"].value("max_connections", 1000);
        }

        // Parse WebRTC config
        if (j.contains("webrtc")) {
            webrtc.enable_dtls = j["webrtc"].value("enable_dtls", true);
            webrtc.enable_rtp_rtcp_mux = j["webrtc"].value("enable_rtp_rtcp_mux", true);

            // Parse ice_servers array
            if (j["webrtc"].contains("ice_servers")) {
                for (const auto& server : j["webrtc"]["ice_servers"]) {
                    IceServer ice_server;
                    if (server.contains("urls")) {
                        ice_server.urls = server["urls"].get<std::vector<std::string>>();
                    }
                    webrtc.ice_servers.push_back(ice_server);
                }
            }
        }

        // Parse rooms config
        if (j.contains("rooms")) {
            rooms.max_rooms = j["rooms"].value("max_rooms", 100);
            rooms.max_viewers_per_room = j["rooms"].value("max_viewers_per_room", 100);
            rooms.idle_timeout_seconds = j["rooms"].value("idle_timeout_seconds", 300);
        }

        // Parse video config
        if (j.contains("video")) {
            video.codec = j["video"].value("codec", "VP8");
            video.max_bitrate_kbps = j["video"].value("max_bitrate_kbps", 2500);
            video.min_bitrate_kbps = j["video"].value("min_bitrate_kbps", 500);
            video.target_bitrate_kbps = j["video"].value("target_bitrate_kbps", 1500);
            video.max_framerate = j["video"].value("max_framerate", 30);
        }

        // Parse audio config
        if (j.contains("audio")) {
            audio.codec = j["audio"].value("codec", "Opus");
            audio.bitrate_kbps = j["audio"].value("bitrate_kbps", 128);
            audio.sample_rate = j["audio"].value("sample_rate", 48000);
        }

        // Parse logging config
        if (j.contains("logging")) {
            logging.level = j["logging"].value("level", "info");
            logging.file = j["logging"].value("file", "media_server.log");
            logging.console = j["logging"].value("console", true);
        }

        std::cout << "Configuration loaded successfully:" << std::endl;
        std::cout << "  Server: " << server.host << ":" << server.port << std::endl;
        std::cout << "  Max connections: " << server.max_connections << std::endl;
        std::cout << "  Max rooms: " << rooms.max_rooms << std::endl;
        std::cout << "  Max viewers per room: " << rooms.max_viewers_per_room << std::endl;
        std::cout << "  Video codec: " << video.codec << " ("
                  << video.target_bitrate_kbps << " kbps)" << std::endl;
        std::cout << "  Audio codec: " << audio.codec << " ("
                  << audio.bitrate_kbps << " kbps)" << std::endl;
        std::cout << "  ICE servers: " << webrtc.ice_servers.size() << std::endl;
        std::cout << "  Logging: level=" << logging.level
                  << ", console=" << (logging.console ? "enabled" : "disabled") << std::endl;

        return true;

    } catch (const json::parse_error& e) {
        std::cerr << "JSON parsing error at byte " << e.byte
                  << ": " << e.what() << std::endl;
        return false;
    } catch (const json::type_error& e) {
        std::cerr << "JSON type error: " << e.what() << std::endl;
        return false;
    } catch (const json::exception& e) {
        std::cerr << "JSON error: " << e.what() << std::endl;
        return false;
    } catch (const std::exception& e) {
        std::cerr << "Config loading error: " << e.what() << std::endl;
        return false;
    }
}

} // namespace onlylang