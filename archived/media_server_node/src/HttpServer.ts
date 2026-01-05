// /**
//  * HttpServer - Handles HTTP API endpoints matching C++ server API
//  */

// import express, { Express, Request, Response } from 'express';
// import { CreateRoomRequest, CreateRoomResponse } from './types';
// import RoomManager from './RoomManager';
// import { ServerConfig } from './types';

// export class HttpServer {
//   private app: Express;
//   private roomManager: RoomManager;
//   private config: ServerConfig;
//   private server: any;

//   constructor(roomManager: RoomManager, config: ServerConfig) {
//     this.app = express();
//     this.roomManager = roomManager;
//     this.config = config;

//     this.setupMiddleware();
//     this.setupRoutes();
//   }

//   private setupMiddleware(): void {
//     this.app.use(express.json());
//     this.app.use(express.urlencoded({ extended: true }));

//     // CORS middleware
//     this.app.use((req, res, next) => {
//       res.header('Access-Control-Allow-Origin', '*');
//       res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
//       res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept, Authorization');

//       if (req.method === 'OPTIONS') {
//         res.sendStatus(200);
//       } else {
//         next();
//       }
//     });

//     // Logging middleware
//     this.app.use((req, res, next) => {
//       console.log(`${req.method} ${req.path}`);
//       next();
//     });
//   }

//   private setupRoutes(): void {
//     /**
//      * Health check endpoint
//      * GET /health
//      */
//     this.app.get('/health', (req: Request, res: Response) => {
//       res.json({ status: 'healthy' });
//     });

//     /**
//      * Create a new room
//      * POST /room/create
//      * Body: { post_id: string, host_user_id: string }
//      */
//     this.app.post('/room/create', async (req: Request, res: Response) => {
//       try {
//         const { post_id, host_user_id } = req.body as CreateRoomRequest;

//         if (!post_id || !host_user_id) {
//           return res.status(400).json({
//             error: 'Missing required fields: post_id, host_user_id'
//           });
//         }

//         const roomId = await this.roomManager.createRoom(post_id, host_user_id);

//         const websocketUrl = `ws://${this.config.server.host}:${this.config.server.websocket_port}/room/${roomId}/host`;

//         const response: CreateRoomResponse = {
//           room_id: roomId,
//           websocket_url: websocketUrl,
//           status: 'created'
//         };

//         res.status(201).json(response);
//       } catch (error: any) {
//         console.error('Error creating room:', error);
//         res.status(500).json({
//           error: error.message || 'Failed to create room'
//         });
//       }
//     });

//     /**
//      * Stop a room
//      * POST /room/:room_id/stop
//      */
//     this.app.post('/room/:room_id/stop', async (req: Request, res: Response) => {
//       try {
//         const { room_id } = req.params;

//         const success = await this.roomManager.deleteRoom(room_id);

//         if (!success) {
//           return res.status(404).json({
//             error: `Room ${room_id} not found`
//           });
//         }

//         res.json({
//           status: 'ok',
//           room_id: room_id
//         });
//       } catch (error: any) {
//         console.error('Error stopping room:', error);
//         res.status(500).json({
//           error: error.message || 'Failed to stop room'
//         });
//       }
//     });

//     /**
//      * Get room statistics
//      * GET /room/:room_id/stats
//      */
//     this.app.get('/room/:room_id/stats', (req: Request, res: Response) => {
//       try {
//         const { room_id } = req.params;

//         const stats = this.roomManager.getRoomStats(room_id);

//         if (!stats) {
//           return res.status(404).json({
//             error: `Room ${room_id} not found`
//           });
//         }

//         res.json(stats);
//       } catch (error: any) {
//         console.error('Error getting room stats:', error);
//         res.status(500).json({
//           error: error.message || 'Failed to get room stats'
//         });
//       }
//     });

//     /**
//      * Get server statistics
//      * GET /stats
//      */
//     this.app.get('/stats', (req: Request, res: Response) => {
//       try {
//         const stats = this.roomManager.getServerStats();
//         res.json(stats);
//       } catch (error: any) {
//         console.error('Error getting server stats:', error);
//         res.status(500).json({
//           error: error.message || 'Failed to get server stats'
//         });
//       }
//     });

//     // 404 handler
//     this.app.use((req: Request, res: Response) => {
//       res.status(404).json({
//         error: 'Endpoint not found'
//       });
//     });
//   }

//   /**
//    * Start the HTTP server
//    */
//   start(): Promise<void> {
//     return new Promise((resolve, reject) => {
//       try {
//         this.server = this.app.listen(
//           this.config.server.port,
//           this.config.server.host,
//           () => {
//             console.log(
//               `✓ HTTP server listening on ${this.config.server.host}:${this.config.server.port}`
//             );
//             resolve();
//           }
//         );

//         this.server.on('error', (error: Error) => {
//           console.error('HTTP server error:', error);
//           reject(error);
//         });
//       } catch (error) {
//         reject(error);
//       }
//     });
//   }

//   /**
//    * Stop the HTTP server
//    */
//   stop(): Promise<void> {
//     return new Promise((resolve) => {
//       if (this.server) {
//         this.server.close(() => {
//           console.log('HTTP server stopped');
//           resolve();
//         });
//       } else {
//         resolve();
//       }
//     });
//   }
// }

// export default HttpServer;
