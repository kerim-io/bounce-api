// /**
//  * Configuration loader for mediasoup server
//  * Reads config.json and provides typed configuration
//  * Environment variables override config.json values
//  */

// import * as fs from 'fs';
// import * as path from 'path';
// import * as dotenv from 'dotenv';
// import { ServerConfig } from './types';

// // Load environment variables
// dotenv.config();

// /**
//  * Parse TURN server configuration from environment variables
//  * Supports: TURN_URL, TURN_USERNAME, TURN_CREDENTIAL
//  */
// function parseTurnServerFromEnv(): { urls: string[]; username?: string; credential?: string } | null {
//   const turnUrl = process.env.TURN_URL;
//   if (!turnUrl) return null;

//   return {
//     urls: [turnUrl],
//     username: process.env.TURN_USERNAME,
//     credential: process.env.TURN_CREDENTIAL
//   };
// }

// /**
//  * Build ICE servers array from environment and defaults
//  */
// function buildIceServers(): Array<{ urls: string[]; username?: string; credential?: string }> {
//   const iceServers: Array<{ urls: string[]; username?: string; credential?: string }> = [];

//   // Add STUN server (always needed)
//   const stunUrl = process.env.STUN_URL || 'stun:stun.l.google.com:19302';
//   iceServers.push({ urls: [stunUrl] });

//   // Add TURN server if configured
//   const turnServer = parseTurnServerFromEnv();
//   if (turnServer) {
//     iceServers.push(turnServer);
//   }

//   return iceServers;
// }

// export class Config {
//   private static instance: Config;
//   private config: ServerConfig;

//   private constructor() {
//     // Default configuration (can be overridden by config.json or ENV vars)
//     this.config = {
//       server: {
//         host: process.env.HOST || '0.0.0.0',
//         port: parseInt(process.env.PORT || '9001', 10),
//         websocket_port: parseInt(process.env.WEBSOCKET_PORT || '9002', 10),
//         max_connections: parseInt(process.env.MAX_CONNECTIONS || '1000', 10),
//         announced_ip: process.env.ANNOUNCED_IP || undefined
//       },
//       webrtc: {
//         ice_servers: buildIceServers(),
//         enable_dtls: true,
//         enable_rtp_rtcp_mux: true
//       },
//       rooms: {
//         max_rooms: parseInt(process.env.MAX_ROOMS || '100', 10),
//         max_viewers_per_room: parseInt(process.env.MAX_VIEWERS_PER_ROOM || '100', 10),
//         idle_timeout_seconds: parseInt(process.env.IDLE_TIMEOUT_SECONDS || '300', 10)
//       },
//       video: {
//         codec: process.env.VIDEO_CODEC || 'VP8',
//         max_bitrate_kbps: parseInt(process.env.MAX_BITRATE_KBPS || '2500', 10),
//         min_bitrate_kbps: parseInt(process.env.MIN_BITRATE_KBPS || '500', 10),
//         target_bitrate_kbps: parseInt(process.env.TARGET_BITRATE_KBPS || '1500', 10),
//         max_framerate: parseInt(process.env.MAX_FRAMERATE || '30', 10)
//       },
//       audio: {
//         codec: process.env.AUDIO_CODEC || 'Opus',
//         bitrate_kbps: parseInt(process.env.AUDIO_BITRATE_KBPS || '128', 10),
//         sample_rate: parseInt(process.env.AUDIO_SAMPLE_RATE || '48000', 10)
//       },
//       logging: {
//         level: process.env.LOG_LEVEL || 'info',
//         file: process.env.LOG_FILE || 'media_server.log',
//         console: process.env.LOG_TO_CONSOLE !== 'false'
//       }
//     };
//   }

//   static getInstance(): Config {
//     if (!Config.instance) {
//       Config.instance = new Config();
//     }
//     return Config.instance;
//   }

//   load(configPath: string = 'config.json'): boolean {
//     try {
//       const fullPath = path.resolve(configPath);

//       if (!fs.existsSync(fullPath)) {
//         console.warn(`Config file not found at ${fullPath}, using defaults`);
//         console.log(`✓ Using environment variables and defaults`);
//         return false;
//       }

//       const fileContents = fs.readFileSync(fullPath, 'utf-8');
//       const loadedConfig = JSON.parse(fileContents);

//       // Merge: config.json provides base, but ENV variables take precedence
//       const mergedConfig = {
//         server: {
//           ...loadedConfig.server,
//           host: process.env.HOST || loadedConfig.server?.host || this.config.server.host,
//           port: parseInt(process.env.PORT || loadedConfig.server?.port || this.config.server.port.toString(), 10),
//           websocket_port: parseInt(process.env.WEBSOCKET_PORT || loadedConfig.server?.websocket_port || this.config.server.websocket_port.toString(), 10),
//           max_connections: parseInt(process.env.MAX_CONNECTIONS || loadedConfig.server?.max_connections || this.config.server.max_connections.toString(), 10),
//           announced_ip: process.env.ANNOUNCED_IP || loadedConfig.server?.announced_ip || undefined
//         },
//         webrtc: {
//           ...this.config.webrtc,
//           ...(loadedConfig.webrtc || {}),
//           // Merge ICE servers: ENV takes precedence, then config.json, then defaults
//           ice_servers: this.mergeIceServers(loadedConfig.webrtc?.ice_servers)
//         },
//         rooms: {
//           ...loadedConfig.rooms,
//           max_rooms: parseInt(process.env.MAX_ROOMS || loadedConfig.rooms?.max_rooms || this.config.rooms.max_rooms.toString(), 10),
//           max_viewers_per_room: parseInt(process.env.MAX_VIEWERS_PER_ROOM || loadedConfig.rooms?.max_viewers_per_room || this.config.rooms.max_viewers_per_room.toString(), 10),
//           idle_timeout_seconds: parseInt(process.env.IDLE_TIMEOUT_SECONDS || loadedConfig.rooms?.idle_timeout_seconds || this.config.rooms.idle_timeout_seconds.toString(), 10)
//         },
//         video: {
//           ...loadedConfig.video,
//           codec: process.env.VIDEO_CODEC || loadedConfig.video?.codec || this.config.video.codec,
//           max_bitrate_kbps: parseInt(process.env.MAX_BITRATE_KBPS || loadedConfig.video?.max_bitrate_kbps || this.config.video.max_bitrate_kbps.toString(), 10),
//           min_bitrate_kbps: parseInt(process.env.MIN_BITRATE_KBPS || loadedConfig.video?.min_bitrate_kbps || this.config.video.min_bitrate_kbps.toString(), 10),
//           target_bitrate_kbps: parseInt(process.env.TARGET_BITRATE_KBPS || loadedConfig.video?.target_bitrate_kbps || this.config.video.target_bitrate_kbps.toString(), 10),
//           max_framerate: parseInt(process.env.MAX_FRAMERATE || loadedConfig.video?.max_framerate || this.config.video.max_framerate.toString(), 10)
//         },
//         audio: {
//           ...loadedConfig.audio,
//           codec: process.env.AUDIO_CODEC || loadedConfig.audio?.codec || this.config.audio.codec,
//           bitrate_kbps: parseInt(process.env.AUDIO_BITRATE_KBPS || loadedConfig.audio?.bitrate_kbps || this.config.audio.bitrate_kbps.toString(), 10),
//           sample_rate: parseInt(process.env.AUDIO_SAMPLE_RATE || loadedConfig.audio?.sample_rate || this.config.audio.sample_rate.toString(), 10)
//         },
//         logging: {
//           ...loadedConfig.logging,
//           level: process.env.LOG_LEVEL || loadedConfig.logging?.level || this.config.logging.level,
//           file: process.env.LOG_FILE || loadedConfig.logging?.file || this.config.logging.file,
//           console: process.env.LOG_TO_CONSOLE !== 'false' && (loadedConfig.logging?.console !== false)
//         }
//       };

//       this.config = mergedConfig;

//       console.log(`✓ Configuration loaded from ${fullPath} with ENV overrides`);
//       console.log(`  Server will run on ${this.config.server.host}:${this.config.server.port}`);
//       console.log(`  WebSocket will run on port ${this.config.server.websocket_port}`);
//       return true;
//     } catch (error) {
//       console.error(`Failed to load config: ${error}`);
//       return false;
//     }
//   }

//   get(): ServerConfig {
//     return this.config;
//   }

//   /**
//    * Merge ICE servers from config.json with environment variables
//    * ENV variables take highest precedence
//    */
//   private mergeIceServers(configIceServers?: Array<{ urls: string[]; username?: string; credential?: string; _enable?: boolean }>): Array<{ urls: string[]; username?: string; credential?: string }> {
//     // If TURN is configured via ENV, use buildIceServers (includes both STUN and TURN)
//     const envTurn = process.env.TURN_URL;
//     if (envTurn) {
//       return buildIceServers();
//     }

//     // Otherwise, use config.json ice_servers if available, else use defaults
//     if (configIceServers && configIceServers.length > 0) {
//       // Filter out disabled servers (those with _enable: false)
//       const enabledServers = configIceServers
//         .filter(server => server._enable !== false)
//         .map(({ urls, username, credential }) => ({ urls, username, credential }));

//       if (enabledServers.length > 0) {
//         return enabledServers;
//       }
//     }

//     return this.config.webrtc.ice_servers;
//   }

//   /**
//    * Validate configuration for production environment
//    * Throws error if critical settings are missing
//    */
//   validateForProduction(): void {
//     const isProduction = process.env.NODE_ENV === 'production';

//     if (!isProduction) {
//       return;
//     }

//     const errors: string[] = [];

//     // ANNOUNCED_IP is required in production
//     if (!this.config.server.announced_ip) {
//       errors.push('ANNOUNCED_IP must be set in production. Set it to your server\'s public IP address.');
//     }

//     // Check for TURN server in production (warning only, not blocking)
//     const hasTurn = this.config.webrtc.ice_servers.some(
//       server => server.urls.some(url => url.startsWith('turn:') || url.startsWith('turns:'))
//     );

//     if (!hasTurn) {
//       console.warn('⚠️  WARNING: No TURN server configured. ~15-20% of users behind symmetric NAT will fail to connect.');
//       console.warn('   Set TURN_URL, TURN_USERNAME, and TURN_CREDENTIAL environment variables.');
//     }

//     if (errors.length > 0) {
//       console.error('❌ Production configuration validation failed:');
//       errors.forEach(err => console.error(`   - ${err}`));
//       throw new Error(`Production configuration invalid: ${errors.join('; ')}`);
//     }

//     console.log('✓ Production configuration validated');
//     console.log(`  ANNOUNCED_IP: ${this.config.server.announced_ip}`);
//     console.log(`  ICE Servers: ${this.config.webrtc.ice_servers.length} configured`);
//     if (hasTurn) {
//       console.log('  TURN Server: configured');
//     }
//   }

//   /**
//    * Get ICE servers for client-side configuration
//    * Returns the ice_servers array that should be passed to RTCPeerConnection
//    */
//   getIceServersForClient(): Array<{ urls: string[]; username?: string; credential?: string }> {
//     return this.config.webrtc.ice_servers;
//   }
// }

// export default Config;
