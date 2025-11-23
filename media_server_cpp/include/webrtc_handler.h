#ifndef WEBRTC_HANDLER_H
#define WEBRTC_HANDLER_H

#include <string>
#include <memory>
#include <functional>
#include <vector>
#include <atomic>
#include <mutex>

namespace onlylang {

enum class SignalingState {
    STABLE,
    HAVE_LOCAL_OFFER,
    HAVE_REMOTE_OFFER,
    HAVE_LOCAL_PRANSWER,
    HAVE_REMOTE_PRANSWER,
    CLOSED
};

enum class IceConnectionState {
    NEW,
    CHECKING,
    CONNECTED,
    COMPLETED,
    FAILED,
    DISCONNECTED,
    CLOSED
};

struct SdpOffer {
    std::string type;
    std::string sdp;
};

struct SdpAnswer {
    std::string type;
    std::string sdp;
};

struct IceCandidate {
    std::string candidate;
    std::string sdp_mid;
    int sdp_mline_index;
};

struct MediaTrack {
    std::string track_id;
    std::string kind;
    bool enabled;
};

class WebRTCHandler {
public:
    using IceCandidateCallback = std::function<void(const IceCandidate&)>;
    using StateChangeCallback = std::function<void(IceConnectionState)>;
    using TrackCallback = std::function<void(const MediaTrack&)>;
    using DataCallback = std::function<void(const std::vector<uint8_t>&)>;

    WebRTCHandler(const std::string& peer_id);
    ~WebRTCHandler();

    bool initialize();
    void close();

    SdpOffer create_offer();
    SdpAnswer create_answer(const SdpOffer& offer);
    bool set_remote_description(const std::string& type, const std::string& sdp);
    bool set_local_description(const std::string& type, const std::string& sdp);

    bool add_ice_candidate(const IceCandidate& candidate);

    void set_ice_candidate_callback(IceCandidateCallback callback);
    void set_state_change_callback(StateChangeCallback callback);
    void set_track_callback(TrackCallback callback);
    void set_data_callback(DataCallback callback);

    bool add_audio_track(const std::string& track_id);
    bool add_video_track(const std::string& track_id);
    bool remove_track(const std::string& track_id);

    bool send_data(const std::vector<uint8_t>& data);

    SignalingState get_signaling_state() const;
    IceConnectionState get_ice_state() const;

    std::string get_peer_id() const { return peer_id_; }
    bool is_connected() const;

    struct Stats {
        uint64_t bytes_sent;
        uint64_t bytes_received;
        uint64_t packets_sent;
        uint64_t packets_received;
        uint64_t packets_lost;
        double current_round_trip_time;
    };
    Stats get_stats() const;

private:
    std::string peer_id_;
    std::atomic<bool> initialized_;
    std::atomic<bool> closed_;

    SignalingState signaling_state_;
    IceConnectionState ice_state_;

    std::string local_sdp_;
    std::string remote_sdp_;
    std::vector<IceCandidate> ice_candidates_;
    std::vector<MediaTrack> local_tracks_;

    IceCandidateCallback ice_candidate_callback_;
    StateChangeCallback state_change_callback_;
    TrackCallback track_callback_;
    DataCallback data_callback_;

    mutable std::mutex mutex_;

    Stats stats_;

    void on_ice_candidate_internal(const IceCandidate& candidate);
    void on_state_change_internal(IceConnectionState state);
    void on_track_internal(const MediaTrack& track);
    void update_stats();

    // Helper methods for SDP generation
    std::string generate_random_string(size_t length);
    std::string generate_fingerprint();
    uint32_t generate_ssrc();
};

} // namespace onlylang

#endif // WEBRTC_HANDLER_H