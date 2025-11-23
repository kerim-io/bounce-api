#ifndef STREAMING_SERVER_H
#define STREAMING_SERVER_H

#include <string>
#include <memory>
#include <map>
#include <mutex>
#include <atomic>
#include "room_manager.h"
#include "webrtc_handler.h"

namespace onlylang {

class HttpServer;

struct StreamingConfig {
    std::string host;
    int port;
    int max_rooms;
    int max_viewers_per_room;
};

struct PeerConnection {
    std::string peer_id;
    std::string room_id;
    std::string user_id;
    ParticipantRole role;
    std::shared_ptr<WebRTCHandler> handler;
    std::chrono::steady_clock::time_point created_at;
    bool is_active;
};

class StreamingServer : public std::enable_shared_from_this<StreamingServer> {
public:
    StreamingServer();
    ~StreamingServer();

    bool initialize(const StreamingConfig& config);
    bool start();
    void stop();

    std::string create_room(const std::string& post_id, const std::string& host_user_id);
    bool delete_room(const std::string& room_id);

    std::string add_peer(const std::string& room_id, const std::string& user_id,
                        const std::string& username, ParticipantRole role);

    bool remove_peer(const std::string& peer_id);

    SdpOffer create_offer(const std::string& peer_id);
    SdpAnswer process_offer(const std::string& peer_id, const SdpOffer& offer);
    bool process_answer(const std::string& peer_id, const SdpAnswer& answer);
    bool add_ice_candidate(const std::string& peer_id, const IceCandidate& candidate);

    PeerConnection* get_peer(const std::string& peer_id);
    Room* get_room(const std::string& room_id);

    std::shared_ptr<RoomManager> get_room_manager() { return room_manager_; }

    struct ServerStats {
        int total_rooms;
        int active_rooms;
        int total_peers;
        int total_viewers;
        int total_hosts;
        uint64_t total_bytes_sent;
        uint64_t total_bytes_received;
    };
    ServerStats get_stats();

private:
    std::shared_ptr<RoomManager> room_manager_;
    std::shared_ptr<HttpServer> http_server_;

    std::map<std::string, PeerConnection> peers_;
    std::mutex peers_mutex_;

    StreamingConfig config_;
    std::atomic<bool> running_;
    std::atomic<bool> initialized_;

    std::string generate_room_id();
    std::string generate_peer_id();

    void on_ice_candidate(const std::string& peer_id, const IceCandidate& candidate);
    void on_peer_state_change(const std::string& peer_id, IceConnectionState state);

    void forward_media_to_viewers(const std::string& room_id, const std::string& host_peer_id);
    void cleanup_disconnected_peers();
};

} // namespace onlylang

#endif // STREAMING_SERVER_H