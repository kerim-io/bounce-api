#include "room_manager_simple.h"
#include <chrono>

namespace onlylang {

bool RoomManager::create_room(const std::string& room_id,
                              const std::string& classroom_id,
                              const std::string& host_user_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    // Check if room already exists
    if (rooms_.find(room_id) != rooms_.end()) {
        return false;
    }

    Room room;
    room.room_id = room_id;
    room.classroom_id = classroom_id;
    room.host_user_id = host_user_id;
    room.is_active = true;
    room.created_at = std::chrono::steady_clock::now();
    room.last_activity = room.created_at;
    // participants map is initially empty, host_stream stays nullptr

    rooms_.emplace(room_id, std::move(room));
    return true;
}

// Stub implementations for the remaining methods – can be filled in later

bool RoomManager::delete_room(const std::string& room_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    return rooms_.erase(room_id) > 0;
}

bool RoomManager::room_exists(const std::string& room_id) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return rooms_.find(room_id) != rooms_.end();
}

bool RoomManager::add_participant(const std::string& room_id,
                                   const std::string& user_id,
                                   const std::string& username,
                                   ParticipantRole role,
                                   std::shared_ptr<WebRTCHandler> handler) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    Participant participant{user_id, username, role, handler,
                            std::chrono::steady_clock::now(), true};
    it->second.participants[user_id] = std::move(participant);
    return true;
}

bool RoomManager::remove_participant(const std::string& room_id,
                                    const std::string& user_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = rooms_.find(room_id);
    if (it == rooms_.end()) return false;
    return it->second.participants.erase(user_id) > 0;
}

Room* RoomManager::get_room(const std::string& room_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = rooms_.find(room_id);
    return it != rooms_.end() ? &it->second : nullptr;
}

std::vector<std::string> RoomManager::get_active_rooms() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> active;
    for (const auto& kv : rooms_) {
        if (kv.second.is_active) {
            active.push_back(kv.first);
        }
    }
    return active;
}

int RoomManager::get_total_rooms() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return static_cast<int>(rooms_.size());
}

int RoomManager::get_total_participants() const {
    std::lock_guard<std::mutex> lock(mutex_);
    int total = 0;
    for (const auto& kv : rooms_) {
        total += static_cast<int>(kv.second.participants.size());
    }
    return total;
}

void RoomManager::cleanup_idle_rooms(int timeout_seconds) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto now = std::chrono::steady_clock::now();
    for (auto it = rooms_.begin(); it != rooms_.end(); ) {
        auto idle = std::chrono::duration_cast<std::chrono::seconds>(
            now - it->second.last_activity).count();
        if (idle > timeout_seconds) {
            it = rooms_.erase(it);
        } else {
            ++it;
        }
    }
}

RoomManager::Stats RoomManager::get_stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    Stats s{};
    s.total_rooms = static_cast<int>(rooms_.size());
    for (const auto& kv : rooms_) {
        const Room& r = kv.second;
        if (r.is_active) ++s.active_rooms;
        for (const auto& p : r.participants) {
            if (!p.second.is_active) continue;
            ++s.total_participants;
            if (p.second.role == ParticipantRole::HOST) ++s.total_hosts;
            else if (p.second.role == ParticipantRole::VIEWER) ++s.total_viewers;
        }
    }
    return s;
}

} // namespace onlylang
