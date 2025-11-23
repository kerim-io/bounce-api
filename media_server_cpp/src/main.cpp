#include "streaming_server.h"
#include "config.h"
#include <iostream>
#include <signal.h>
#include <thread>
#include <chrono>

using namespace onlylang;

static std::shared_ptr<StreamingServer> g_server;
static bool g_running = true;

void signal_handler(int signal) {
    std::cout << "\nReceived signal " << signal << ", shutting down..." << std::endl;
    g_running = false;
    if (g_server) {
        g_server->stop();
    }
}

int main(int argc, char* argv[]) {
    std::cout << "========================================" << std::endl;
    std::cout << "  BitBasel Media Server" << std::endl;
    std::cout << "  Live Streaming for Art Basel Miami" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << std::endl;

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    std::string config_file = "config.json";
    if (argc > 1) {
        config_file = argv[1];
    }

    std::cout << "Loading configuration from: " << config_file << std::endl;

    Config& config = Config::instance();
    if (!config.load(config_file)) {
        std::cerr << "Warning: Failed to load config file, using defaults" << std::endl;
    }

    g_server = std::make_shared<StreamingServer>();

    StreamingConfig stream_config;
    stream_config.host = config.server.host;
    stream_config.port = config.server.port;
    stream_config.max_rooms = config.rooms.max_rooms;
    stream_config.max_viewers_per_room = config.rooms.max_viewers_per_room;

    std::cout << "Initializing streaming server..." << std::endl;
    if (!g_server->initialize(stream_config)) {
        std::cerr << "Failed to initialize streaming server" << std::endl;
        return 1;
    }

    std::cout << "Starting streaming server..." << std::endl;
    if (!g_server->start()) {
        std::cerr << "Failed to start streaming server" << std::endl;
        return 1;
    }

    std::cout << std::endl;
    std::cout << "Media server running on " << config.server.host << ":" << config.server.port << std::endl;
    std::cout << "Max rooms: " << config.rooms.max_rooms << std::endl;
    std::cout << "Max viewers per room: " << config.rooms.max_viewers_per_room << std::endl;
    std::cout << std::endl;
    std::cout << "HTTP API endpoints:" << std::endl;
    std::cout << "  POST /room/create                - Create a new room" << std::endl;
    std::cout << "  POST /room/:room_id/stop          - Stop a room" << std::endl;
    std::cout << "  GET  /room/:room_id/stats         - Get room statistics" << std::endl;
    std::cout << "  GET  /stats                       - Get server statistics" << std::endl;
    std::cout << "  GET  /health                      - Health check" << std::endl;
    std::cout << std::endl;
    std::cout << "Press Ctrl+C to shutdown" << std::endl;
    std::cout << "========================================" << std::endl;

    int cleanup_counter = 0;
    while (g_running) {
        std::this_thread::sleep_for(std::chrono::seconds(1));

        cleanup_counter++;
        if (cleanup_counter >= 30) {
            cleanup_counter = 0;

            auto room_manager = g_server->get_room_manager();
            if (room_manager) {
                room_manager->cleanup_idle_rooms(config.rooms.idle_timeout_seconds);
            }

            auto stats = g_server->get_stats();
            if (stats.total_rooms > 0 || stats.total_peers > 0) {
                std::cout << "Stats: " << stats.active_rooms << "/" << stats.total_rooms
                          << " rooms, " << stats.total_peers << " peers ("
                          << stats.total_hosts << " hosts, " << stats.total_viewers << " viewers), "
                          << "Sent: " << stats.total_bytes_sent << " bytes, "
                          << "Received: " << stats.total_bytes_received << " bytes" << std::endl;
            }
        }
    }

    std::cout << "Shutting down media server..." << std::endl;
    g_server->stop();
    g_server.reset();

    std::cout << "Media server stopped. Goodbye!" << std::endl;
    return 0;
}