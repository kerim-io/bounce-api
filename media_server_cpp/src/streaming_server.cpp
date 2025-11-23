#include "streaming_server.h"
#include "http_server.h"
#include <iostream>
#include <sstream>
#include <random>
#include <iomanip>
#include <chrono>   // <-- added for std::chrono::steady_clock

namespace onlylang {

StreamingServer::StreamingServer()
    : running_(false), initialized_(false) {
}

StreamingServer::~StreamingServer() {
    stop();
}

bool StreamingServer::initialize(const StreamingConfig& config) {
    if (initialized_) {
        return true;
    }

    config_ = config;

    room_manager_ = std::make_shared<RoomManager>();

    http_server_ = std::make_shared<HttpServer>(
        config.host,
        config.port,
        room_manager_,
        shared_from_this()
    );

    initialized_ = true;
    return true;
}

bool StreamingServer::start() {
    if (!initialized_) {
        std::cerr << "StreamingServer not initialized" << std::endl;
        return false;
    }

    if (running_) {
        return true;
    }

    if (!http_server_->start()) {
        std::cerr << "Failed to start HTTP server" << std::endl;
        return false;
    }

    running_ = true;
    std::cout << "Streaming server started successfully" << std::endl;

    return true;
}

void StreamingServer::stop() {
    if (!running_) {
        return;
    }

    running_ = false;

    if (http_server_) {
        http_server_->stop();
    }

    std::lock_guard<std::mutex> lock(peers_mutex_);
    peers_.clear();

    std::cout << "Streaming server stopped" << std::endl;
}

std::string StreamingServer::create_room(const std::string& post_id, const std::string& host_user_id) {
    std::string room_id = generate_room_id();

    if (!room_manager_->create_room(room_id, post_id, host_user_id)) {
        std::cerr << "Failed to create room in room manager" << std::endl;
        return "";
    }

    std::cout << "Created room: " << room_id << " for post: " << post_id << std::endl;
    return room_id;
}

bool StreamingServer::delete_room(const std::string& room_id) {
    Room* room = room_manager_->get_room(room_id);
    if (!room) {
        return false;
    }

    std::vector<std::string> peers_to_remove;
    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        for (const auto& [peer_id, peer] : peers_) {
            if (peer.room_id == room_id) {
                peers_to_remove.push_back(peer_id);
            }
        }
    }

    for (const auto& peer_id : peers_to_remove) {
        remove_peer(peer_id);
    }

    return room_manager_->delete_room(room_id);
}

std::string StreamingServer::add_peer(const std::string& room_id, const std::string& user_id,
                                     const std::string& username, ParticipantRole role) {
    Room* room = room_manager_->get_room(room_id);
    if (!room) {
        std::cerr << "Room not found: " << room_id << std::endl;
        return "";
    }

    std::string peer_id = generate_peer_id();

    auto handler = std::make_shared<WebRTCHandler>(peer_id);
    if (!handler->initialize()) {
        std::cerr << "Failed to initialize WebRTC handler" << std::endl;
        return "";
    }

    handler->set_ice_candidate_callback([this, peer_id](const IceCandidate& candidate) {
        on_ice_candidate(peer_id, candidate);
    });

    handler->set_state_change_callback([this, peer_id](IceConnectionState state) {
        on_peer_state_change(peer_id, state);
    });

    if (!room_manager_->add_participant(room_id, user_id, username, role, handler)) {
        std::cerr << "Failed to add participant to room" << std::endl;
        return "";
    }

    PeerConnection peer;
    peer.peer_id = peer_id;
    peer.room_id = room_id;
    peer.user_id = user_id;
    peer.role = role;
    peer.handler = handler;
    peer.created_at = std::chrono::steady_clock::now();
    peer.is_active = true;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        peers_[peer_id] = peer;
    }

    std::cout << "Added peer: " << peer_id << " to room: " << room_id
              << " as " << (role == ParticipantRole::HOST ? "HOST" : "VIEWER") << std::endl;

    return peer_id;
}

bool StreamingServer::remove_peer(const std::string& peer_id) {
    std::string room_id;
    std::string user_id;
    std::shared_ptr<WebRTCHandler> handler;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        auto it = peers_.find(peer_id);
        if (it == peers_.end()) {
            return false;
        }

        room_id = it->second.room_id;
        user_id = it->second.user_id;
        handler = it->second.handler;
        peers_.erase(it);
    }

    if (handler) {
        handler->close();
    }

    room_manager_->remove_participant(room_id, user_id);

    std::cout << "Removed peer: " << peer_id << " from room: " << room_id << std::endl;

    return true;
}

SdpOffer StreamingServer::create_offer(const std::string& peer_id) {
    std::shared_ptr<WebRTCHandler> handler;
    ParticipantRole role;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        auto it = peers_.find(peer_id);
        if (it == peers_.end() || !it->second.handler) {
            return SdpOffer{"", ""};
        }
        handler = it->second.handler;
        role = it->second.role;
    }

    if (role == ParticipantRole::HOST) {
        handler->add_audio_track("audio_" + peer_id);
        handler->add_video_track("video_" + peer_id);
    }

    return handler->create_offer();
}

SdpAnswer StreamingServer::process_offer(const std::string& peer_id, const SdpOffer& offer) {
    std::shared_ptr<WebRTCHandler> handler;
    ParticipantRole role;
    std::string room_id;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        auto it = peers_.find(peer_id);
        if (it == peers_.end() || !it->second.handler) {
            return SdpAnswer{"", ""};
        }
        handler = it->second.handler;
        role = it->second.role;
        room_id = it->second.room_id;
    }

    handler->set_remote_description(offer.type, offer.sdp);
    SdpAnswer answer = handler->create_answer(offer);

    if (role == ParticipantRole::HOST) {
        forward_media_to_viewers(room_id, peer_id);
    }

    return answer;
}

bool StreamingServer::process_answer(const std::string& peer_id, const SdpAnswer& answer) {
    std::shared_ptr<WebRTCHandler> handler;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        auto it = peers_.find(peer_id);
        if (it == peers_.end() || !it->second.handler) {
            return false;
        }
        handler = it->second.handler;
    }

    return handler->set_remote_description(answer.type, answer.sdp);
}

bool StreamingServer::add_ice_candidate(const std::string& peer_id, const IceCandidate& candidate) {
    std::shared_ptr<WebRTCHandler> handler;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        auto it = peers_.find(peer_id);
        if (it == peers_.end() || !it->second.handler) {
            return false;
        }
        handler = it->second.handler;
    }

    return handler->add_ice_candidate(candidate);
}

PeerConnection* StreamingServer::get_peer(const std::string& peer_id) {
    std::lock_guard<std::mutex> lock(peers_mutex_);

    auto it = peers_.find(peer_id);
    if (it == peers_.end()) {
        return nullptr;
    }

    return &it->second;
}

Room* StreamingServer::get_room(const std::string& room_id) {
    return room_manager_->get_room(room_id);
}

StreamingServer::ServerStats StreamingServer::get_stats() {
    auto room_stats = room_manager_->get_stats();

    ServerStats stats;
    stats.total_rooms = room_stats.total_rooms;
    stats.active_rooms = room_stats.active_rooms;
    stats.total_hosts = room_stats.total_hosts;
    stats.total_viewers = room_stats.total_viewers;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        stats.total_peers = static_cast<int>(peers_.size());

        stats.total_bytes_sent = 0;
        stats.total_bytes_received = 0;

        for (const auto& [peer_id, peer] : peers_) {
            if (peer.handler) {
                auto peer_stats = peer.handler->get_stats();
                stats.total_bytes_sent += peer_stats.bytes_sent;
                stats.total_bytes_received += peer_stats.bytes_received;
            }
        }
    }

    return stats;
}

std::string StreamingServer::generate_room_id() {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_int_distribution<> dis(100000, 999999);

    std::ostringstream oss;
    oss << "room_" << dis(gen);
    return oss.str();
}

std::string StreamingServer::generate_peer_id() {
    static std::random_device rd;
    static std::mt19937 gen(rd());
    static std::uniform_int_distribution<> dis(0, 255);

    std::ostringstream oss;
    oss << "peer_";
    for (int i = 0; i < 8; ++i) {
        oss << std::hex << std::setw(2) << std::setfill('0') << dis(gen);
    }

    return oss.str();
}

void StreamingServer::on_ice_candidate(const std::string& peer_id, const IceCandidate& candidate) {
    std::cout << "ICE candidate generated for peer: " << peer_id << std::endl;
}

void StreamingServer::on_peer_state_change(const std::string& peer_id, IceConnectionState state) {
    std::string state_str;
    switch (state) {
        case IceConnectionState::NEW: state_str = "NEW"; break;
        case IceConnectionState::CHECKING: state_str = "CHECKING"; break;
        case IceConnectionState::CONNECTED: state_str = "CONNECTED"; break;
        case IceConnectionState::COMPLETED: state_str = "COMPLETED"; break;
        case IceConnectionState::FAILED: state_str = "FAILED"; break;
        case IceConnectionState::DISCONNECTED: state_str = "DISCONNECTED"; break;
        case IceConnectionState::CLOSED: state_str = "CLOSED"; break;
    }

    std::cout << "Peer " << peer_id << " state changed to: " << state_str << std::endl;

    if (state == IceConnectionState::FAILED || state == IceConnectionState::CLOSED) {
        remove_peer(peer_id);
    }
}

void StreamingServer::forward_media_to_viewers(const std::string& room_id, const std::string& host_peer_id) {
    Room* room = room_manager_->get_room(room_id);
    if (!room) {
        return;
    }

    std::lock_guard<std::mutex> lock(peers_mutex_);

    for (const auto& [user_id, participant] : room->participants) {
        if (participant.role == ParticipantRole::VIEWER && participant.is_active) {
            for (const auto& [peer_id, peer] : peers_) {
                if (peer.user_id == user_id && peer.room_id == room_id && peer.handler) {
                    std::cout << "Forwarding media from host " << host_peer_id
                              << " to viewer peer " << peer_id << std::endl;
                }
            }
        }
    }
}

void StreamingServer::cleanup_disconnected_peers() {
    std::vector<std::string> peers_to_remove;

    {
        std::lock_guard<std::mutex> lock(peers_mutex_);
        for (const auto& [peer_id, peer] : peers_) {
            if (peer.handler && !peer.handler->is_connected()) {
                auto now = std::chrono::steady_clock::now();
                auto duration = std::chrono::duration_cast<std::chrono::seconds>(
                    now - peer.created_at).count();

                if (duration > 30) {
                    peers_to_remove.push_back(peer_id);
                }
            }
        }
    }

    for (const auto& peer_id : peers_to_remove) {
        std::cout << "Cleaning up disconnected peer: " << peer_id << std::endl;
        remove_peer(peer_id);
    }
}

} // namespace onlylang