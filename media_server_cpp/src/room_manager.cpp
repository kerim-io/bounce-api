#include "room_manager.h"
#include <algorithm>
#include <iostream>

namespace onlylang {

bool RoomManager::create_room(const std::string& room_id, const std::string& post_id,
                               const std::string& host_user_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (rooms_.find(room_id) != rooms_.end()) {
        return false;
    }

    Room room;
    room.room_id = room_id;
    room.post_id = post_id;  // Changed from classroom_id
    room.host_user_id = host_user_id;
    room.is_active = true;
    room.created_at = std::chrono::steady_clock::now();
    room.last_activity = std::chrono::steady_clock::now();

    rooms_[room_id] = room;
    return true;
}

bool RoomManager::delete_room(const std::string& room_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) {
        return false;
    }

    rooms_.erase(it);
    return true;
}

bool RoomManager::room_exists(const std::string& room_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    return rooms_.find(room_id) != rooms_.end();
}

bool RoomManager::add_participant(const std::string& room_id, const std::string& user_id,
                                  const std::string& username, ParticipantRole role,
                                  std::shared_ptr<WebRTCHandler> handler) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) {
        return false;
    }

    Participant participant;
    participant.user_id = user_id;
    participant.username = username;
    participant.role = role;
    participant.webrtc_handler = handler;
    participant.joined_at = std::chrono::steady_clock::now();
    participant.is_active = true;

    it->second.participants[user_id] = participant;
    it->second.last_activity = std::chrono::steady_clock::now();

    return true;
}

bool RoomManager::remove_participant(const std::string& room_id, const std::string& user_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto room_it = rooms_.find(room_id);
    if (room_it == rooms_.end()) {
        return false;
    }

    auto participant_it = room_it->second.participants.find(user_id);
    if (participant_it == room_it->second.participants.end()) {
        return false;
    }

    room_it->second.participants.erase(participant_it);
    room_it->second.last_activity = std::chrono::steady_clock::now();

    return true;
}

Room* RoomManager::get_room(const std::string& room_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) {
        return nullptr;
    }

    return &it->second;
}

std::vector<std::string> RoomManager::get_active_rooms() {
    std::lock_guard<std::mutex> lock(mutex_);

    std::vector<std::string> active_rooms;
    for (const auto& [room_id, room] : rooms_) {
        if (room.is_active) {
            active_rooms.push_back(room_id);
        }
    }

    return active_rooms;
}

int RoomManager::get_total_rooms() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return static_cast<int>(rooms_.size());
}

int RoomManager::get_total_participants() const {
    std::lock_guard<std::mutex> lock(mutex_);

    int total = 0;
    for (const auto& [room_id, room] : rooms_) {
        total += static_cast<int>(room.participants.size());
    }

    return total;
}

void RoomManager::cleanup_idle_rooms(int timeout_seconds) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto now = std::chrono::steady_clock::now();
    std::vector<std::string> rooms_to_delete;

    for (const auto& [room_id, room] : rooms_) {
        auto idle_time = std::chrono::duration_cast<std::chrono::seconds>(
            now - room.last_activity).count();

        if (idle_time > timeout_seconds) {
            rooms_to_delete.push_back(room_id);
        }
    }

    for (const auto& room_id : rooms_to_delete) {
        rooms_.erase(room_id);
        std::cout << "Cleaned up idle room: " << room_id << std::endl;
    }
}

RoomManager::Stats RoomManager::get_stats() {
    std::lock_guard<std::mutex> lock(mutex_);

    Stats stats;
    stats.total_rooms = static_cast<int>(rooms_.size());
    stats.active_rooms = 0;
    stats.total_participants = 0;
    stats.total_viewers = 0;
    stats.total_hosts = 0;

    for (const auto& [room_id, room] : rooms_) {
        if (room.is_active) {
            stats.active_rooms++;
        }

        for (const auto& [user_id, participant] : room.participants) {
            if (participant.is_active) {
                stats.total_participants++;
                if (participant.role == ParticipantRole::VIEWER) {
                    stats.total_viewers++;
                } else if (participant.role == ParticipantRole::HOST) {
                    stats.total_hosts++;
                }
            }
        }
    }

    return stats;
}

} // namespace onlylang