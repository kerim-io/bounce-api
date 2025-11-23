#include "webrtc_handler.h"
#include <iostream>
#include <sstream>
#include <random>
#include <iomanip>
#include <algorithm>   // <-- added for std::find_if
#include <ctime>       // <-- added for std::time

namespace onlylang {

WebRTCHandler::WebRTCHandler(const std::string& peer_id)
    : peer_id_(peer_id),
      initialized_(false),
      closed_(false),
      signaling_state_(SignalingState::STABLE),
      ice_state_(IceConnectionState::NEW) {
    stats_.bytes_sent = 0;
    stats_.bytes_received = 0;
    stats_.packets_sent = 0;
    stats_.packets_received = 0;
    stats_.packets_lost = 0;
    stats_.current_round_trip_time = 0.0;
}

WebRTCHandler::~WebRTCHandler() {
    close();
}

bool WebRTCHandler::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);

    if (initialized_) {
        return true;
    }

    signaling_state_ = SignalingState::STABLE;
    ice_state_ = IceConnectionState::NEW;
    initialized_ = true;

    return true;
}

void WebRTCHandler::close() {
    std::lock_guard<std::mutex> lock(mutex_);

    if (closed_) {
        return;
    }

    signaling_state_ = SignalingState::CLOSED;
    ice_state_ = IceConnectionState::CLOSED;
    closed_ = true;

    local_tracks_.clear();
    ice_candidates_.clear();
}

SdpOffer WebRTCHandler::create_offer() {
    std::lock_guard<std::mutex> lock(mutex_);

    std::ostringstream sdp;
    sdp << "v=0\r\n";
    sdp << "o=- " << std::time(nullptr) << " 2 IN IP4 127.0.0.1\r\n";
    sdp << "s=-\r\n";
    sdp << "t=0 0\r\n";

    sdp << "a=group:BUNDLE 0";
    if (!local_tracks_.empty()) {
        for (size_t i = 0; i < local_tracks_.size(); ++i) {
            sdp << " " << (i + 1);
        }
    }
    sdp << "\r\n";

    sdp << "a=msid-semantic: WMS *\r\n";

    sdp << "m=application 9 UDP/TLS/RTP/SAVPF 127\r\n";
    sdp << "c=IN IP4 0.0.0.0\r\n";
    sdp << "a=ice-ufrag:" << generate_random_string(16) << "\r\n";
    sdp << "a=ice-pwd:" << generate_random_string(24) << "\r\n";
    sdp << "a=ice-options:trickle\r\n";
    sdp << "a=fingerprint:sha-256 " << generate_fingerprint() << "\r\n";
    sdp << "a=setup:actpass\r\n";
    sdp << "a=mid:0\r\n";
    sdp << "a=sendrecv\r\n";

    for (const auto& track : local_tracks_) {
        if (track.kind == "audio") {
            sdp << "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n";
            sdp << "c=IN IP4 0.0.0.0\r\n";
            sdp << "a=rtcp:9 IN IP4 0.0.0.0\r\n";
            sdp << "a=ice-ufrag:" << generate_random_string(16) << "\r\n";
            sdp << "a=ice-pwd:" << generate_random_string(24) << "\r\n";
            sdp << "a=ice-options:trickle\r\n";
            sdp << "a=fingerprint:sha-256 " << generate_fingerprint() << "\r\n";
            sdp << "a=setup:actpass\r\n";
            sdp << "a=mid:audio\r\n";
            sdp << "a=sendrecv\r\n";
            sdp << "a=rtcp-mux\r\n";
            sdp << "a=rtpmap:111 opus/48000/2\r\n";
            sdp << "a=fmtp:111 minptime=10;useinbandfec=1\r\n";
            sdp << "a=ssrc:" << generate_ssrc() << " cname:" << peer_id_ << "\r\n";
            sdp << "a=ssrc:" << generate_ssrc() << " msid:" << track.track_id << " audio\r\n";
        } else if (track.kind == "video") {
            sdp << "m=video 9 UDP/TLS/RTP/SAVPF 96\r\n";
            sdp << "c=IN IP4 0.0.0.0\r\n";
            sdp << "a=rtcp:9 IN IP4 0.0.0.0\r\n";
            sdp << "a=ice-ufrag:" << generate_random_string(16) << "\r\n";
            sdp << "a=ice-pwd:" << generate_random_string(24) << "\r\n";
            sdp << "a=ice-options:trickle\r\n";
            sdp << "a=fingerprint:sha-256 " << generate_fingerprint() << "\r\n";
            sdp << "a=setup:actpass\r\n";
            sdp << "a=mid:video\r\n";
            sdp << "a=sendrecv\r\n";
            sdp << "a=rtcp-mux\r\n";
            sdp << "a=rtcp-rsize\r\n";
            sdp << "a=rtpmap:96 VP8/90000\r\n";
            sdp << "a=rtcp-fb:96 goog-remb\r\n";
            sdp << "a=rtcp-fb:96 transport-cc\r\n";
            sdp << "a=rtcp-fb:96 ccm fir\r\n";
            sdp << "a=rtcp-fb:96 nack\r\n";
            sdp << "a=rtcp-fb:96 nack pli\r\n";
            sdp << "a=ssrc:" << generate_ssrc() << " cname:" << peer_id_ << "\r\n";
            sdp << "a=ssrc:" << generate_ssrc() << " msid:" << track.track_id << " video\r\n";
        }
    }

    local_sdp_ = sdp.str();
    signaling_state_ = SignalingState::HAVE_LOCAL_OFFER;

    SdpOffer offer;
    offer.type = "offer";
    offer.sdp = local_sdp_;

    return offer;
}

SdpAnswer WebRTCHandler::create_answer(const SdpOffer& offer) {
    std::lock_guard<std::mutex> lock(mutex_);

    remote_sdp_ = offer.sdp;
    signaling_state_ = SignalingState::HAVE_REMOTE_OFFER;

    std::ostringstream sdp;
    sdp << "v=0\r\n";
    sdp << "o=- " << std::time(nullptr) << " 2 IN IP4 127.0.0.1\r\n";
    sdp << "s=-\r\n";
    sdp << "t=0 0\r\n";

    sdp << "a=group:BUNDLE 0\r\n";
    sdp << "a=msid-semantic: WMS *\r\n";

    sdp << "m=application 9 UDP/TLS/RTP/SAVPF 127\r\n";
    sdp << "c=IN IP4 0.0.0.0\r\n";
    sdp << "a=ice-ufrag:" << generate_random_string(16) << "\r\n";
    sdp << "a=ice-pwd:" << generate_random_string(24) << "\r\n";
    sdp << "a=ice-options:trickle\r\n";
    sdp << "a=fingerprint:sha-256 " << generate_fingerprint() << "\r\n";
    sdp << "a=setup:active\r\n";
    sdp << "a=mid:0\r\n";
    sdp << "a=sendrecv\r\n";

    local_sdp_ = sdp.str();
    signaling_state_ = SignalingState::STABLE;

    SdpAnswer answer;
    answer.type = "answer";
    answer.sdp = local_sdp_;

    return answer;
}

bool WebRTCHandler::set_remote_description(const std::string& type, const std::string& sdp) {
    std::lock_guard<std::mutex> lock(mutex_);

    remote_sdp_ = sdp;

    if (type == "offer") {
        signaling_state_ = SignalingState::HAVE_REMOTE_OFFER;
    } else if (type == "answer") {
        signaling_state_ = SignalingState::STABLE;
    }

    return true;
}

bool WebRTCHandler::set_local_description(const std::string& type, const std::string& sdp) {
    std::lock_guard<std::mutex> lock(mutex_);

    local_sdp_ = sdp;

    if (type == "offer") {
        signaling_state_ = SignalingState::HAVE_LOCAL_OFFER;
    } else if (type == "answer") {
        signaling_state_ = SignalingState::STABLE;
    }

    return true;
}

bool WebRTCHandler::add_ice_candidate(const IceCandidate& candidate) {
    std::lock_guard<std::mutex> lock(mutex_);

    ice_candidates_.push_back(candidate);

    if (ice_state_ == IceConnectionState::NEW) {
        ice_state_ = IceConnectionState::CHECKING;
        on_state_change_internal(ice_state_);
    }

    return true;
}

void WebRTCHandler::set_ice_candidate_callback(IceCandidateCallback callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    ice_candidate_callback_ = callback;
}

void WebRTCHandler::set_state_change_callback(StateChangeCallback callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    state_change_callback_ = callback;
}

void WebRTCHandler::set_track_callback(TrackCallback callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    track_callback_ = callback;
}

void WebRTCHandler::set_data_callback(DataCallback callback) {
    std::lock_guard<std::mutex> lock(mutex_);
    data_callback_ = callback;
}

bool WebRTCHandler::add_audio_track(const std::string& track_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    MediaTrack track;
    track.track_id = track_id;
    track.kind = "audio";
    track.enabled = true;

    local_tracks_.push_back(track);
    return true;
}

bool WebRTCHandler::add_video_track(const std::string& track_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    MediaTrack track;
    track.track_id = track_id;
    track.kind = "video";
    track.enabled = true;

    local_tracks_.push_back(track);
    return true;
}

bool WebRTCHandler::remove_track(const std::string& track_id) {
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = std::find_if(local_tracks_.begin(), local_tracks_.end(),
        [&track_id](const MediaTrack& track) {
            return track.track_id == track_id;
        });

    if (it != local_tracks_.end()) {
        local_tracks_.erase(it);
        return true;
    }

    return false;
}

bool WebRTCHandler::send_data(const std::vector<uint8_t>& data) {
    std::lock_guard<std::mutex> lock(mutex_);

    if (ice_state_ != IceConnectionState::CONNECTED &&
        ice_state_ != IceConnectionState::COMPLETED) {
        return false;
    }

    stats_.bytes_sent += data.size();
    stats_.packets_sent++;

    return true;
}

SignalingState WebRTCHandler::get_signaling_state() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return signaling_state_;
}

IceConnectionState WebRTCHandler::get_ice_state() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return ice_state_;
}

bool WebRTCHandler::is_connected() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return (ice_state_ == IceConnectionState::CONNECTED ||
            ice_state_ == IceConnectionState::COMPLETED) &&
           signaling_state_ == SignalingState::STABLE;
}

WebRTCHandler::Stats WebRTCHandler::get_stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return stats_;
}

void WebRTCHandler::on_ice_candidate_internal(const IceCandidate& candidate) {
    if (ice_candidate_callback_) {
        ice_candidate_callback_(candidate);
    }
}

void WebRTCHandler::on_state_change_internal(IceConnectionState state) {
    if (state_change_callback_) {
        state_change_callback_(state);
    }
}

void WebRTCHandler::on_track_internal(const MediaTrack& track) {
    if (track_callback_) {
        track_callback_(track);
    }
}

void WebRTCHandler::update_stats() {
    stats_.current_round_trip_time = 0.05;
}

std::string WebRTCHandler::generate_random_string(size_t length) {
    static const char alphanum[] =
        "0123456789"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz";

    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, sizeof(alphanum) - 2);

    std::string result;
    result.reserve(length);

    for (size_t i = 0; i < length; ++i) {
        result += alphanum[dis(gen)];
    }

    return result;
}

std::string WebRTCHandler::generate_fingerprint() {
    std::ostringstream oss;
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 255);

    for (int i = 0; i < 32; ++i) {
        if (i > 0) oss << ":";
        oss << std::hex << std::setw(2) << std::setfill('0') << dis(gen);
    }

    return oss.str();
}

uint32_t WebRTCHandler::generate_ssrc() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<uint32_t> dis(1000000, 9999999);
    return dis(gen);
}

} // namespace onlylang