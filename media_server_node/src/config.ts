/**
 * Configuration loader for mediasoup server
 * Reads config.json and provides typed configuration
 * Environment variables override config.json values
 */

import * as fs from 'fs';
import * as path from 'path';
import * as dotenv from 'dotenv';
import { ServerConfig } from './types';

// Load environment variables
dotenv.config();

export class Config {
  private static instance: Config;
  private config: ServerConfig;

  private constructor() {
    // Default configuration (can be overridden by config.json or ENV vars)
    this.config = {
      server: {
        host: process.env.HOST || '0.0.0.0',
        port: parseInt(process.env.PORT || '9001', 10),
        websocket_port: parseInt(process.env.WEBSOCKET_PORT || '9002', 10),
        max_connections: parseInt(process.env.MAX_CONNECTIONS || '1000', 10)
      },
      webrtc: {
        ice_servers: [
          {
            urls: ['stun:stun.l.google.com:19302']
          }
        ],
        enable_dtls: true,
        enable_rtp_rtcp_mux: true
      },
      rooms: {
        max_rooms: parseInt(process.env.MAX_ROOMS || '100', 10),
        max_viewers_per_room: parseInt(process.env.MAX_VIEWERS_PER_ROOM || '100', 10),
        idle_timeout_seconds: parseInt(process.env.IDLE_TIMEOUT_SECONDS || '300', 10)
      },
      video: {
        codec: process.env.VIDEO_CODEC || 'VP8',
        max_bitrate_kbps: parseInt(process.env.MAX_BITRATE_KBPS || '2500', 10),
        min_bitrate_kbps: parseInt(process.env.MIN_BITRATE_KBPS || '500', 10),
        target_bitrate_kbps: parseInt(process.env.TARGET_BITRATE_KBPS || '1500', 10),
        max_framerate: parseInt(process.env.MAX_FRAMERATE || '30', 10)
      },
      audio: {
        codec: process.env.AUDIO_CODEC || 'Opus',
        bitrate_kbps: parseInt(process.env.AUDIO_BITRATE_KBPS || '128', 10),
        sample_rate: parseInt(process.env.AUDIO_SAMPLE_RATE || '48000', 10)
      },
      logging: {
        level: process.env.LOG_LEVEL || 'info',
        file: process.env.LOG_FILE || 'media_server.log',
        console: process.env.LOG_TO_CONSOLE !== 'false'
      }
    };
  }

  static getInstance(): Config {
    if (!Config.instance) {
      Config.instance = new Config();
    }
    return Config.instance;
  }

  load(configPath: string = 'config.json'): boolean {
    try {
      const fullPath = path.resolve(configPath);

      if (!fs.existsSync(fullPath)) {
        console.warn(`Config file not found at ${fullPath}, using defaults`);
        console.log(`✓ Using environment variables and defaults`);
        return false;
      }

      const fileContents = fs.readFileSync(fullPath, 'utf-8');
      const loadedConfig = JSON.parse(fileContents);

      // Merge: config.json provides base, but ENV variables take precedence
      const mergedConfig = {
        server: {
          ...loadedConfig.server,
          host: process.env.HOST || loadedConfig.server?.host || this.config.server.host,
          port: parseInt(process.env.PORT || loadedConfig.server?.port || this.config.server.port.toString(), 10),
          websocket_port: parseInt(process.env.WEBSOCKET_PORT || loadedConfig.server?.websocket_port || this.config.server.websocket_port.toString(), 10),
          max_connections: parseInt(process.env.MAX_CONNECTIONS || loadedConfig.server?.max_connections || this.config.server.max_connections.toString(), 10)
        },
        webrtc: { ...this.config.webrtc, ...(loadedConfig.webrtc || {}) },
        rooms: {
          ...loadedConfig.rooms,
          max_rooms: parseInt(process.env.MAX_ROOMS || loadedConfig.rooms?.max_rooms || this.config.rooms.max_rooms.toString(), 10),
          max_viewers_per_room: parseInt(process.env.MAX_VIEWERS_PER_ROOM || loadedConfig.rooms?.max_viewers_per_room || this.config.rooms.max_viewers_per_room.toString(), 10),
          idle_timeout_seconds: parseInt(process.env.IDLE_TIMEOUT_SECONDS || loadedConfig.rooms?.idle_timeout_seconds || this.config.rooms.idle_timeout_seconds.toString(), 10)
        },
        video: {
          ...loadedConfig.video,
          codec: process.env.VIDEO_CODEC || loadedConfig.video?.codec || this.config.video.codec,
          max_bitrate_kbps: parseInt(process.env.MAX_BITRATE_KBPS || loadedConfig.video?.max_bitrate_kbps || this.config.video.max_bitrate_kbps.toString(), 10),
          min_bitrate_kbps: parseInt(process.env.MIN_BITRATE_KBPS || loadedConfig.video?.min_bitrate_kbps || this.config.video.min_bitrate_kbps.toString(), 10),
          target_bitrate_kbps: parseInt(process.env.TARGET_BITRATE_KBPS || loadedConfig.video?.target_bitrate_kbps || this.config.video.target_bitrate_kbps.toString(), 10),
          max_framerate: parseInt(process.env.MAX_FRAMERATE || loadedConfig.video?.max_framerate || this.config.video.max_framerate.toString(), 10)
        },
        audio: {
          ...loadedConfig.audio,
          codec: process.env.AUDIO_CODEC || loadedConfig.audio?.codec || this.config.audio.codec,
          bitrate_kbps: parseInt(process.env.AUDIO_BITRATE_KBPS || loadedConfig.audio?.bitrate_kbps || this.config.audio.bitrate_kbps.toString(), 10),
          sample_rate: parseInt(process.env.AUDIO_SAMPLE_RATE || loadedConfig.audio?.sample_rate || this.config.audio.sample_rate.toString(), 10)
        },
        logging: {
          ...loadedConfig.logging,
          level: process.env.LOG_LEVEL || loadedConfig.logging?.level || this.config.logging.level,
          file: process.env.LOG_FILE || loadedConfig.logging?.file || this.config.logging.file,
          console: process.env.LOG_TO_CONSOLE !== 'false' && (loadedConfig.logging?.console !== false)
        }
      };

      this.config = mergedConfig;

      console.log(`✓ Configuration loaded from ${fullPath} with ENV overrides`);
      console.log(`  Server will run on ${this.config.server.host}:${this.config.server.port}`);
      console.log(`  WebSocket will run on port ${this.config.server.websocket_port}`);
      return true;
    } catch (error) {
      console.error(`Failed to load config: ${error}`);
      return false;
    }
  }

  get(): ServerConfig {
    return this.config;
  }
}

export default Config;
