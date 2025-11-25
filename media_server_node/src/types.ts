/**
 * Type definitions for BitBasel mediasoup server
 * Matches the API contract of the C++ media server
 */

export interface ServerConfig {
  server: {
    host: string;
    port: number;
    websocket_port: number;
    max_connections: number;
    announced_ip?: string;  // Public IP for WebRTC (required in production)
  };
  webrtc: {
    ice_servers: Array<{
      urls: string[];
      username?: string;
      credential?: string;
    }>;
    enable_dtls: boolean;
    enable_rtp_rtcp_mux: boolean;
  };
  rooms: {
    max_rooms: number;
    max_viewers_per_room: number;
    idle_timeout_seconds: number;
  };
  video: {
    codec: string;
    max_bitrate_kbps: number;
    min_bitrate_kbps: number;
    target_bitrate_kbps: number;
    max_framerate: number;
  };
  audio: {
    codec: string;
    bitrate_kbps: number;
    sample_rate: number;
  };
  logging: {
    level: string;
    file: string;
    console: boolean;
  };
}

export interface Room {
  room_id: string;
  post_id: string;
  host_user_id: string;
  host_peer_id?: string;
  created_at: Date;
  is_active: boolean;
  viewer_count: number;
  max_viewers: number;
  router?: any; // mediasoup.Router
}

export interface Peer {
  peer_id: string;
  room_id: string;
  user_id: string;
  username?: string;
  role: 'host' | 'viewer';
  is_active: boolean;
  created_at: Date;
  sendTransport?: any; // mediasoup.WebRtcTransport
  recvTransport?: any; // mediasoup.WebRtcTransport
  producers: Map<string, any>; // Map of producer_id -> mediasoup.Producer
  consumers: Map<string, any>; // Map of consumer_id -> mediasoup.Consumer
}

export interface CreateRoomRequest {
  post_id: string;
  host_user_id: string;
}

export interface CreateRoomResponse {
  room_id: string;
  websocket_url: string;
  status: string;
}

export interface RoomStats {
  room_id: string;
  post_id: string;
  host_user_id: string;
  is_active: boolean;
  viewer_count: number;
  created_at: string;
  bytes_sent: number;
  bytes_received: number;
}

export interface ServerStats {
  total_rooms: number;
  active_rooms: number;
  total_peers: number;
  total_viewers: number;
  total_hosts: number;
  total_bytes_sent: number;
  total_bytes_received: number;
  rooms: RoomStats[];
}

export interface WebSocketMessage {
  type: 'offer' | 'answer' | 'ice-candidate' | 'join' | 'leave' | 'error' | 'viewer-joined' | 'viewer-left' |
        'getTransport' | 'connectTransport' | 'produce' | 'consume' | 'getRouterRtpCapabilities' | 'produceData';
  data?: any;
  room_id?: string;
  peer_id?: string;
  sdp?: string;
  candidate?: any;
  error?: string;
  rtpParameters?: any;
  rtpCapabilities?: any;
  producerId?: string;
  kind?: 'audio' | 'video';
  appData?: any;
}
