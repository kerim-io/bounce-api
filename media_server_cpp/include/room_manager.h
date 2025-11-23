#ifndef ROOM_MANAGER_H
#define ROOM_MANAGER_H

#include <string>
#include <map>
#include <vector>
#include <memory>
#include <mutex>
#include <chrono>

namespace onlylang {

class WebRTCHandler;

enum class ParticipantRole {
    HOST,
    VIEWER
};

struct Participant {
    std::string user_id;
    std::string username;
    ParticipantRole role;
    std::shared_ptr<WebRTCHandler> webrtc_handler;
    std::chrono::steady_clock::time_point joined_at;
    bool is_active;
};

struct Room {
    std::string room_id;
    std::string post_id;  // Changed from classroom_id to post_id
    std::string host_user_id;
    bool is_active;
    std::chrono::steady_clock::time_point created_at;
    std::chrono::steady_clock::time_point last_activity;
    std::map<std::string, Participant> participants;
    void* host_stream;

    Room() : is_active(false), host_stream(nullptr) {}

    int viewer_count() const {
        int count = 0;
        for (const auto& [id, participant] : participants) {
            if (participant.role == ParticipantRole::VIEWER && participant.is_active) {
                count++;
            }
        }
        return count;
    }

    bool has_host() const {
        for (const auto& [id, participant] : participants) {
            if (participant.role == ParticipantRole::HOST && participant.is_active) {
                return true;
            }
        }
        return false;
    }
};

class RoomManager {
public:
    RoomManager() = default;
    ~RoomManager() = default;

    bool create_room(const std::string& room_id, const std::string& post_id,
                     const std::string& host_user_id);
    bool delete_room(const std::string& room_id);
    bool room_exists(const std::string& room_id);

    bool add_participant(const std::string& room_id, const std::string& user_id,
                        const std::string& username, ParticipantRole role,
                        std::shared_ptr<WebRTCHandler> handler);
    bool remove_participant(const std::string& room_id, const std::string& user_id);

    Room* get_room(const std::string& room_id);
    std::vector<std::string> get_active_rooms();
    int get_total_rooms() const;
    int get_total_participants() const;

    void cleanup_idle_rooms(int timeout_seconds);

    struct Stats {
        int total_rooms;
        int active_rooms;
        int total_participants;
        int total_viewers;
        int total_hosts;
    };
    Stats get_stats();

private:
    std::map<std::string, Room> rooms_;
    mutable std::mutex mutex_;
};

} // namespace onlylang

#endif // ROOM_MANAGER_H