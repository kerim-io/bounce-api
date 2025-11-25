/**
 * MediasoupHandler - Manages mediasoup workers, routers, transports, and media streams
 */

import * as mediasoup from 'mediasoup';
import { types as mediasoupTypes } from 'mediasoup';
import { ServerConfig } from './types';

export class MediasoupHandler {
  private workers: mediasoupTypes.Worker[] = [];
  private nextWorkerIdx = 0;
  private config: ServerConfig;

  constructor(config: ServerConfig) {
    this.config = config;
  }

  /**
   * Initialize mediasoup workers
   */
  async initialize(numWorkers: number = 1): Promise<void> {
    console.log(`Initializing ${numWorkers} mediasoup worker(s)...`);

    for (let i = 0; i < numWorkers; i++) {
      const worker = await mediasoup.createWorker({
        logLevel: 'warn',
        logTags: ['info', 'ice', 'dtls', 'rtp', 'srtp', 'rtcp'],
        rtcMinPort: 40000,
        rtcMaxPort: 49999
      });

      worker.on('died', () => {
        console.error(`Worker ${worker.pid} died, exiting in 2 seconds...`);
        setTimeout(() => process.exit(1), 2000);
      });

      this.workers.push(worker);
      console.log(`✓ Worker ${i + 1} created (PID: ${worker.pid})`);
    }
  }

  /**
   * Get next available worker (round-robin)
   */
  private getNextWorker(): mediasoupTypes.Worker {
    const worker = this.workers[this.nextWorkerIdx];
    this.nextWorkerIdx = (this.nextWorkerIdx + 1) % this.workers.length;
    return worker;
  }

  /**
   * Create a new router for a room
   */
  async createRouter(): Promise<mediasoupTypes.Router> {
    const worker = this.getNextWorker();

    const mediaCodecs: mediasoupTypes.RtpCodecCapability[] = [
      {
        kind: 'audio',
        mimeType: 'audio/opus',
        clockRate: 48000,
        channels: 2,
        preferredPayloadType: 111
      },
      {
        kind: 'video',
        mimeType: 'video/VP8',
        clockRate: 90000,
        preferredPayloadType: 96,
        parameters: {
          'x-google-start-bitrate': 1000
        }
      },
      {
        kind: 'video',
        mimeType: 'video/VP9',
        clockRate: 90000,
        preferredPayloadType: 98,
        parameters: {
          'profile-id': 2,
          'x-google-start-bitrate': 1000
        }
      },
      {
        kind: 'video',
        mimeType: 'video/h264',
        clockRate: 90000,
        preferredPayloadType: 102,
        parameters: {
          'packetization-mode': 1,
          'profile-level-id': '42e01f',
          'level-asymmetry-allowed': 1,
          'x-google-start-bitrate': 1000
        }
      }
    ];

    const router = await worker.createRouter({ mediaCodecs });
    return router;
  }

  /**
   * Create WebRTC transport for a peer
   */
  async createWebRtcTransport(
    router: mediasoupTypes.Router
  ): Promise<mediasoupTypes.WebRtcTransport> {
    const {
      maxIncomingBitrate,
      initialAvailableOutgoingBitrate
    } = {
      maxIncomingBitrate: this.config.video.max_bitrate_kbps * 1000,
      initialAvailableOutgoingBitrate: this.config.video.target_bitrate_kbps * 1000
    };

    // Get announced IP from config (centralized configuration)
    const announcedIp = this.config.server.announced_ip;

    // Only warn in development - production enforcement happens in config.validateForProduction()
    if (!announcedIp && process.env.NODE_ENV !== 'production') {
      console.warn('⚠️  ANNOUNCED_IP not set. WebRTC will only work locally.');
      console.warn('   For production, set ANNOUNCED_IP to your server\'s public IP address.');
    }

    const transport = await router.createWebRtcTransport({
      listenIps: [
        {
          ip: '0.0.0.0',
          announcedIp: announcedIp  // Public IP for production, undefined for local dev
        }
      ],
      enableUdp: true,
      enableTcp: true,
      preferUdp: true,
      initialAvailableOutgoingBitrate
    });

    if (maxIncomingBitrate) {
      try {
        await transport.setMaxIncomingBitrate(maxIncomingBitrate);
      } catch (error) {
        console.error('Failed to set max incoming bitrate:', error);
      }
    }

    return transport;
  }

  /**
   * Clean up resources
   */
  async close(): Promise<void> {
    console.log('Closing mediasoup workers...');
    for (const worker of this.workers) {
      worker.close();
    }
    this.workers = [];
  }
}

export default MediasoupHandler;
