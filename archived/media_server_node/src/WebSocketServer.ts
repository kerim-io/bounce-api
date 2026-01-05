// /**
//  * WebSocketServer - Handles WebSocket signaling for WebRTC connections
//  * Full mediasoup implementation with Producer/Consumer management
//  */

// import { Server as WebSocketServer, WebSocket } from 'ws';
// import { IncomingMessage } from 'http';
// import { parse as parseUrl } from 'url';
// import RoomManager from './RoomManager';
// import MediasoupHandler from './MediasoupHandler';
// import Config from './config';
// import { WebSocketMessage } from './types';
// import { types as mediasoupTypes } from 'mediasoup';

// interface WebSocketClient {
//   ws: WebSocket;
//   peerId: string;
//   roomId: string;
//   role: 'host' | 'viewer';
//   userId: string;
//   sendTransport?: mediasoupTypes.WebRtcTransport;
//   recvTransport?: mediasoupTypes.WebRtcTransport;
//   producers: Map<string, mediasoupTypes.Producer>;
//   consumers: Map<string, mediasoupTypes.Consumer>;
// }

// export class WSServer {
//   private wss: WebSocketServer;
//   private roomManager: RoomManager;
//   private mediasoupHandler: MediasoupHandler;
//   private clients: Map<string, WebSocketClient> = new Map();

//   constructor(
//     port: number,
//     roomManager: RoomManager,
//     mediasoupHandler: MediasoupHandler
//   ) {
//     this.roomManager = roomManager;
//     this.mediasoupHandler = mediasoupHandler;

//     this.wss = new WebSocketServer({ port });

//     this.wss.on('connection', (ws: WebSocket, req: IncomingMessage) => {
//       this.handleConnection(ws, req);
//     });

//     console.log(`✓ WebSocket server listening on port ${port}`);
//   }

//   private handleConnection(ws: WebSocket, req: IncomingMessage): void {
//     const url = parseUrl(req.url || '', true);
//     const pathname = url.pathname || '';

//     // Parse path: /room/:room_id/host or /room/:room_id/viewer
//     const match = pathname.match(/^\/room\/([^\/]+)\/(host|viewer)$/);

//     if (!match) {
//       ws.close(1008, 'Invalid WebSocket path');
//       return;
//     }

//     const roomId = match[1];
//     const role = match[2] as 'host' | 'viewer';

//     const room = this.roomManager.getRoom(roomId);
//     if (!room) {
//       ws.close(1008, `Room ${roomId} not found`);
//       return;
//     }

//     const userId = url.query.user_id as string || `user_${Date.now()}`;
//     const username = url.query.username as string || 'Anonymous';

//     this.roomManager
//       .addPeer(roomId, userId, username, role)
//       .then((peerId) => {
//         const client: WebSocketClient = {
//           ws,
//           peerId,
//           roomId,
//           role,
//           userId,
//           producers: new Map(),
//           consumers: new Map()
//         };

//         this.clients.set(peerId, client);

//         console.log(`✓ WebSocket connected: ${peerId} (${role}) in room ${roomId}`);

//         // Send welcome message with router RTP capabilities and ICE servers
//         const room = this.roomManager.getRoom(roomId);
//         if (room && room.router) {
//           // Get ICE servers (includes TURN if configured)
//           const iceServers = Config.getInstance().getIceServersForClient();

//           this.sendMessage(ws, {
//             type: 'join',
//             peer_id: peerId,
//             room_id: roomId,
//             data: {
//               role,
//               rtpCapabilities: room.router.rtpCapabilities,
//               iceServers  // Client needs this for RTCPeerConnection configuration
//             }
//           });
//         }

//         // Setup message handler
//         ws.on('message', (data: Buffer) => {
//           this.handleMessage(peerId, data.toString());
//         });

//         // Handle disconnect
//         ws.on('close', () => {
//           this.handleDisconnect(peerId);
//         });

//         ws.on('error', (error) => {
//           console.error(`WebSocket error for peer ${peerId}:`, error);
//         });

//         // Notify other peers in room
//         if (role === 'viewer') {
//           this.broadcastToRoom(roomId, {
//             type: 'viewer-joined',
//             peer_id: peerId,
//             data: { username }
//           }, peerId);

//           // Create consumers for existing host producers
//           this.createConsumersForViewer(peerId);
//         }
//       })
//       .catch((error) => {
//         console.error('Error adding peer:', error);
//         ws.close(1011, error.message);
//       });
//   }

//   private async handleMessage(peerId: string, data: string): Promise<void> {
//     try {
//       const client = this.clients.get(peerId);
//       if (!client) {
//         console.error(`Client ${peerId} not found`);
//         return;
//       }

//       const message: WebSocketMessage = JSON.parse(data);

//       console.log(`Message from ${peerId} (${client.role}):`, message.type);

//       switch (message.type) {
//         case 'getRouterRtpCapabilities':
//           await this.handleGetRouterRtpCapabilities(client);
//           break;

//         case 'getTransport':
//           await this.handleGetTransport(client, message);
//           break;

//         case 'connectTransport':
//           await this.handleConnectTransport(client, message);
//           break;

//         case 'produce':
//           await this.handleProduce(client, message);
//           break;

//         case 'consume':
//           await this.handleConsume(client, message);
//           break;

//         case 'leave':
//           await this.handleDisconnect(peerId);
//           break;

//         default:
//           console.warn(`Unknown message type: ${message.type}`);
//       }
//     } catch (error) {
//       console.error(`Error handling message from ${peerId}:`, error);
//       this.sendError(peerId, `Failed to process message: ${error}`);
//     }
//   }

//   private async handleGetRouterRtpCapabilities(client: WebSocketClient): Promise<void> {
//     const room = this.roomManager.getRoom(client.roomId);
//     if (!room || !room.router) {
//       throw new Error('Room or router not found');
//     }

//     this.sendMessage(client.ws, {
//       type: 'getRouterRtpCapabilities',
//       data: {
//         rtpCapabilities: room.router.rtpCapabilities
//       }
//     });
//   }

//   private async handleGetTransport(client: WebSocketClient, message: WebSocketMessage): Promise<void> {
//     const room = this.roomManager.getRoom(client.roomId);
//     if (!room || !room.router) {
//       throw new Error('Room or router not found');
//     }

//     const { data } = message;
//     const isSend = data?.type === 'send';

//     // Create WebRTC transport
//     const transport = await this.mediasoupHandler.createWebRtcTransport(room.router);

//     if (isSend) {
//       client.sendTransport = transport;
//     } else {
//       client.recvTransport = transport;
//     }

//     // Send back transport parameters
//     this.sendMessage(client.ws, {
//       type: 'getTransport',
//       data: {
//         transportType: isSend ? 'send' : 'recv',
//         id: transport.id,
//         iceParameters: transport.iceParameters,
//         iceCandidates: transport.iceCandidates,
//         dtlsParameters: transport.dtlsParameters
//       }
//     });

//     console.log(`✓ Created ${isSend ? 'send' : 'recv'} transport for peer ${client.peerId}`);
//   }

//   private async handleConnectTransport(client: WebSocketClient, message: WebSocketMessage): Promise<void> {
//     const { data } = message;
//     const isSend = data?.transportType === 'send';
//     const transport = isSend ? client.sendTransport : client.recvTransport;

//     if (!transport) {
//       throw new Error(`Transport not found for peer ${client.peerId}`);
//     }

//     await transport.connect({
//       dtlsParameters: data.dtlsParameters
//     });

//     this.sendMessage(client.ws, {
//       type: 'connectTransport',
//       data: { connected: true, transportType: data.transportType }
//     });

//     console.log(`✓ Connected ${isSend ? 'send' : 'recv'} transport for peer ${client.peerId}`);
//   }

//   private async handleProduce(client: WebSocketClient, message: WebSocketMessage): Promise<void> {
//     if (client.role !== 'host') {
//       throw new Error('Only hosts can produce');
//     }

//     if (!client.sendTransport) {
//       throw new Error('Send transport not found');
//     }

//     const { data } = message;
//     const { kind, rtpParameters, appData } = data;

//     // Create producer
//     const producer = await client.sendTransport.produce({
//       kind,
//       rtpParameters,
//       appData
//     });

//     client.producers.set(producer.id, producer);

//     console.log(`✓ Producer created: ${producer.id} (${kind}) for host ${client.peerId}`);

//     // Send producer ID back to client
//     this.sendMessage(client.ws, {
//       type: 'produce',
//       data: {
//         producerId: producer.id,
//         kind
//       }
//     });

//     // Create consumers for all viewers in the room
//     this.createConsumersForAllViewers(client.roomId, producer);
//   }

//   private async handleConsume(client: WebSocketClient, message: WebSocketMessage): Promise<void> {
//     if (!client.recvTransport) {
//       throw new Error('Receive transport not found');
//     }

//     const { data } = message;
//     const { producerId, rtpCapabilities } = data;

//     const room = this.roomManager.getRoom(client.roomId);
//     if (!room || !room.router) {
//       throw new Error('Room or router not found');
//     }

//     // Check if router can consume
//     if (!room.router.canConsume({ producerId, rtpCapabilities })) {
//       throw new Error('Cannot consume this producer');
//     }

//     // Create consumer
//     const consumer = await client.recvTransport.consume({
//       producerId,
//       rtpCapabilities,
//       paused: false
//     });

//     client.consumers.set(consumer.id, consumer);

//     console.log(`✓ Consumer created: ${consumer.id} for viewer ${client.peerId}`);

//     // Send consumer parameters
//     this.sendMessage(client.ws, {
//       type: 'consume',
//       data: {
//         consumerId: consumer.id,
//         producerId: producerId,
//         kind: consumer.kind,
//         rtpParameters: consumer.rtpParameters
//       }
//     });
//   }

//   private async createConsumersForViewer(viewerPeerId: string): Promise<void> {
//     const viewer = this.clients.get(viewerPeerId);
//     if (!viewer || viewer.role !== 'viewer') {
//       return;
//     }

//     // Wait a bit for transport creation
//     setTimeout(async () => {
//       if (!viewer.recvTransport) {
//         console.log(`Viewer ${viewerPeerId} recv transport not ready yet`);
//         return;
//       }

//       // Find all host producers in the room
//       this.clients.forEach((client) => {
//         if (client.roomId === viewer.roomId && client.role === 'host') {
//           client.producers.forEach((producer) => {
//             this.notifyViewerOfNewProducer(viewerPeerId, producer.id, producer.kind as 'audio' | 'video');
//           });
//         }
//       });
//     }, 1000);
//   }

//   private async createConsumersForAllViewers(roomId: string, producer: mediasoupTypes.Producer): Promise<void> {
//     this.clients.forEach((client) => {
//       if (client.roomId === roomId && client.role === 'viewer' && client.recvTransport) {
//         this.notifyViewerOfNewProducer(client.peerId, producer.id, producer.kind as 'audio' | 'video');
//       }
//     });
//   }

//   private notifyViewerOfNewProducer(viewerPeerId: string, producerId: string, kind: 'audio' | 'video'): void {
//     const viewer = this.clients.get(viewerPeerId);
//     if (!viewer) {
//       return;
//     }

//     this.sendMessage(viewer.ws, {
//       type: 'produceData',
//       data: {
//         producerId,
//         kind
//       }
//     });
//   }

//   private async handleDisconnect(peerId: string): Promise<void> {
//     const client = this.clients.get(peerId);
//     if (!client) {
//       return;
//     }

//     console.log(`✓ Peer disconnected: ${peerId}`);

//     // Close all producers
//     client.producers.forEach((producer) => {
//       producer.close();
//     });

//     // Close all consumers
//     client.consumers.forEach((consumer) => {
//       consumer.close();
//     });

//     // Close transports
//     if (client.sendTransport) {
//       client.sendTransport.close();
//     }
//     if (client.recvTransport) {
//       client.recvTransport.close();
//     }

//     // Remove peer from room
//     await this.roomManager.removePeer(peerId);

//     // Notify other peers
//     if (client.role === 'viewer') {
//       this.broadcastToRoom(client.roomId, {
//         type: 'viewer-left',
//         peer_id: peerId
//       }, peerId);
//     }

//     // Remove client
//     this.clients.delete(peerId);

//     // Close WebSocket
//     if (client.ws.readyState === WebSocket.OPEN) {
//       client.ws.close();
//     }
//   }

//   private sendMessage(ws: WebSocket, message: WebSocketMessage): void {
//     if (ws.readyState === WebSocket.OPEN) {
//       ws.send(JSON.stringify(message));
//     }
//   }

//   private sendError(peerId: string, error: string): void {
//     const client = this.clients.get(peerId);
//     if (client) {
//       this.sendMessage(client.ws, {
//         type: 'error',
//         error
//       });
//     }
//   }

//   private broadcastToRoom(roomId: string, message: WebSocketMessage, excludePeerId?: string): void {
//     this.clients.forEach((client) => {
//       if (client.roomId === roomId && client.peerId !== excludePeerId) {
//         this.sendMessage(client.ws, message);
//       }
//     });
//   }

//   /**
//    * Close the WebSocket server
//    */
//   close(): void {
//     console.log('Closing WebSocket server...');

//     // Close all client connections
//     this.clients.forEach((client) => {
//       client.producers.forEach((producer) => producer.close());
//       client.consumers.forEach((consumer) => consumer.close());
//       if (client.sendTransport) client.sendTransport.close();
//       if (client.recvTransport) client.recvTransport.close();
//       client.ws.close();
//     });

//     this.clients.clear();

//     // Close server
//     this.wss.close(() => {
//       console.log('✓ WebSocket server closed');
//     });
//   }
// }

// export default WSServer;
