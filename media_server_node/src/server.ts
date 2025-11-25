/**
 * Main server entry point for BitBasel mediasoup media server
 * Drop-in replacement for C++ media server
 */

import Config from './config';
import MediasoupHandler from './MediasoupHandler';
import RoomManager from './RoomManager';
import HttpServer from './HttpServer';
import WSServer from './WebSocketServer';

class MediaServer {
  private config: Config;
  private mediasoupHandler!: MediasoupHandler;
  private roomManager!: RoomManager;
  private httpServer!: HttpServer;
  private wsServer!: WSServer;
  private cleanupInterval?: NodeJS.Timeout;

  constructor() {
    this.config = Config.getInstance();
  }

  async initialize(): Promise<void> {
    console.log('========================================');
    console.log('  BitBasel Media Server (mediasoup)');
    console.log('  Live Streaming for Art Basel Miami');
    console.log('========================================');
    console.log('');

    // Load configuration
    const configPath = process.argv[2] || 'config.json';
    console.log(`Loading configuration from: ${configPath}`);
    this.config.load(configPath);

    // Validate configuration for production environment
    // This will throw an error if ANNOUNCED_IP is not set in production
    this.config.validateForProduction();

    const serverConfig = this.config.get();

    console.log('');
    console.log('Initializing mediasoup...');

    // Initialize mediasoup with workers based on CPU count
    const os = await import('os');
    const numWorkers = Math.max(1, os.cpus().length - 1); // Leave one CPU for other tasks
    console.log(`Initializing ${numWorkers} mediasoup worker(s)...`);

    this.mediasoupHandler = new MediasoupHandler(serverConfig);
    await this.mediasoupHandler.initialize(numWorkers);

    // Initialize room manager
    this.roomManager = new RoomManager(
      this.mediasoupHandler,
      serverConfig.rooms.max_rooms,
      serverConfig.rooms.max_viewers_per_room
    );

    // Initialize HTTP server
    this.httpServer = new HttpServer(this.roomManager, serverConfig);

    // Initialize WebSocket server
    this.wsServer = new WSServer(
      serverConfig.server.websocket_port,
      this.roomManager,
      this.mediasoupHandler
    );

    console.log('');
    console.log('✓ All services initialized');
  }

  async start(): Promise<void> {
    const serverConfig = this.config.get();

    console.log('');
    console.log('Starting servers...');

    // Start HTTP server
    await this.httpServer.start();

    console.log('');
    console.log(`Media server running on ${serverConfig.server.host}:${serverConfig.server.port}`);
    console.log(`Max rooms: ${serverConfig.rooms.max_rooms}`);
    console.log(`Max viewers per room: ${serverConfig.rooms.max_viewers_per_room}`);
    console.log('');
    console.log('HTTP API endpoints:');
    console.log('  POST /room/create                 - Create a new room');
    console.log('  POST /room/:room_id/stop          - Stop a room');
    console.log('  GET  /room/:room_id/stats         - Get room statistics');
    console.log('  GET  /stats                       - Get server statistics');
    console.log('  GET  /health                      - Health check');
    console.log('');
    console.log('WebSocket endpoints:');
    console.log(`  ws://${serverConfig.server.host}:${serverConfig.server.websocket_port}/room/:room_id/host   - Host stream`);
    console.log(`  ws://${serverConfig.server.host}:${serverConfig.server.websocket_port}/room/:room_id/viewer - View stream`);
    console.log('');
    console.log('Press Ctrl+C to shutdown');
    console.log('========================================');

    // Start cleanup interval
    this.startCleanupInterval(serverConfig.rooms.idle_timeout_seconds);
  }

  private startCleanupInterval(idleTimeoutSeconds: number): void {
    // Run cleanup every 30 seconds
    this.cleanupInterval = setInterval(() => {
      this.roomManager.cleanupIdleRooms(idleTimeoutSeconds);

      // Log stats if there are active rooms
      const stats = this.roomManager.getServerStats();
      if (stats.total_rooms > 0 || stats.total_peers > 0) {
        console.log(
          `Stats: ${stats.active_rooms}/${stats.total_rooms} rooms, ` +
          `${stats.total_peers} peers (${stats.total_hosts} hosts, ${stats.total_viewers} viewers)`
        );
      }
    }, 30000);
  }

  async stop(): Promise<void> {
    console.log('');
    console.log('Shutting down media server...');

    // Stop cleanup interval
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
    }

    // Close WebSocket server
    if (this.wsServer) {
      this.wsServer.close();
    }

    // Stop HTTP server
    if (this.httpServer) {
      await this.httpServer.stop();
    }

    // Close mediasoup
    if (this.mediasoupHandler) {
      await this.mediasoupHandler.close();
    }

    console.log('✓ Media server stopped. Goodbye!');
  }
}

// Main execution
async function main() {
  const server = new MediaServer();

  // Handle shutdown signals
  const shutdown = async (signal: string) => {
    console.log(`\nReceived ${signal}, shutting down...`);
    await server.stop();
    process.exit(0);
  };

  process.on('SIGINT', () => shutdown('SIGINT'));
  process.on('SIGTERM', () => shutdown('SIGTERM'));

  // Handle uncaught errors
  process.on('uncaughtException', (error) => {
    console.error('Uncaught exception:', error);
    shutdown('uncaughtException');
  });

  process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled rejection at:', promise, 'reason:', reason);
    shutdown('unhandledRejection');
  });

  try {
    await server.initialize();
    await server.start();
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

// Run the server
main();
