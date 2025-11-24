/**
 * RoomManager - Manages streaming rooms and peers
 */

import { v4 as uuidv4 } from 'uuid';
import { Room, Peer, RoomStats, ServerStats } from './types';
import { types as mediasoupTypes } from 'mediasoup';
import MediasoupHandler from './MediasoupHandler';

export class RoomManager {
  private rooms: Map<string, Room> = new Map();
  private peers: Map<string, Peer> = new Map();
  private mediasoupHandler: MediasoupHandler;
  private maxRooms: number;
  private maxViewersPerRoom: number;

  constructor(
    mediasoupHandler: MediasoupHandler,
    maxRooms: number,
    maxViewersPerRoom: number
  ) {
    this.mediasoupHandler = mediasoupHandler;
    this.maxRooms = maxRooms;
    this.maxViewersPerRoom = maxViewersPerRoom;
  }

  /**
   * Create a new streaming room
   */
  async createRoom(postId: string, hostUserId: string): Promise<string> {
    if (this.rooms.size >= this.maxRooms) {
      throw new Error(`Maximum rooms (${this.maxRooms}) reached`);
    }

    const roomId = uuidv4();
    const router = await this.mediasoupHandler.createRouter();

    const room: Room = {
      room_id: roomId,
      post_id: postId,
      host_user_id: hostUserId,
      created_at: new Date(),
      is_active: true,
      viewer_count: 0,
      max_viewers: this.maxViewersPerRoom,
      router: router
    };

    this.rooms.set(roomId, room);
    console.log(`✓ Room created: ${roomId} for post ${postId}`);

    return roomId;
  }

  /**
   * Delete a room and disconnect all peers
   */
  async deleteRoom(roomId: string): Promise<boolean> {
    const room = this.rooms.get(roomId);
    if (!room) {
      return false;
    }

    // Remove all peers in this room
    const peersToRemove: string[] = [];
    this.peers.forEach((peer, peerId) => {
      if (peer.room_id === roomId) {
        peersToRemove.push(peerId);
      }
    });

    for (const peerId of peersToRemove) {
      await this.removePeer(peerId);
    }

    // Close router
    if (room.router) {
      room.router.close();
    }

    room.is_active = false;
    this.rooms.delete(roomId);

    console.log(`✓ Room deleted: ${roomId}`);
    return true;
  }

  /**
   * Add a peer (host or viewer) to a room
   */
  async addPeer(
    roomId: string,
    userId: string,
    username: string,
    role: 'host' | 'viewer'
  ): Promise<string> {
    const room = this.rooms.get(roomId);
    if (!room) {
      throw new Error(`Room ${roomId} not found`);
    }

    if (role === 'viewer' && room.viewer_count >= room.max_viewers) {
      throw new Error(`Room ${roomId} is full`);
    }

    const peerId = uuidv4();

    const peer: Peer = {
      peer_id: peerId,
      room_id: roomId,
      user_id: userId,
      username: username,
      role: role,
      is_active: true,
      created_at: new Date(),
      producers: new Map(),
      consumers: new Map()
    };

    this.peers.set(peerId, peer);

    if (role === 'viewer') {
      room.viewer_count++;
    } else if (role === 'host') {
      room.host_peer_id = peerId;
    }

    console.log(`✓ Peer added: ${peerId} (${role}) to room ${roomId}`);

    return peerId;
  }

  /**
   * Remove a peer from a room
   */
  async removePeer(peerId: string): Promise<boolean> {
    const peer = this.peers.get(peerId);
    if (!peer) {
      return false;
    }

    const room = this.rooms.get(peer.room_id);

    // Close producers and consumers
    peer.producers.forEach((producer) => producer.close());
    peer.consumers.forEach((consumer) => consumer.close());

    // Close transports
    if (peer.sendTransport) {
      peer.sendTransport.close();
    }
    if (peer.recvTransport) {
      peer.recvTransport.close();
    }

    // Update room viewer count
    if (room && peer.role === 'viewer') {
      room.viewer_count = Math.max(0, room.viewer_count - 1);
    }

    // If host leaves, close the room
    if (room && peer.role === 'host') {
      await this.deleteRoom(peer.room_id);
    }

    this.peers.delete(peerId);
    console.log(`✓ Peer removed: ${peerId}`);

    return true;
  }

  /**
   * Get a room by ID
   */
  getRoom(roomId: string): Room | undefined {
    return this.rooms.get(roomId);
  }

  /**
   * Get a peer by ID
   */
  getPeer(peerId: string): Peer | undefined {
    return this.peers.get(peerId);
  }

  /**
   * Get statistics for a specific room
   */
  getRoomStats(roomId: string): RoomStats | null {
    const room = this.rooms.get(roomId);
    if (!room) {
      return null;
    }

    return {
      room_id: room.room_id,
      post_id: room.post_id,
      host_user_id: room.host_user_id,
      is_active: room.is_active,
      viewer_count: room.viewer_count,
      created_at: room.created_at.toISOString(),
      bytes_sent: 0, // TODO: Implement async stats collection
      bytes_received: 0 // TODO: Implement async stats collection
    };
  }

  /**
   * Get overall server statistics
   */
  getServerStats(): ServerStats {
    let totalViewers = 0;
    let totalHosts = 0;
    let activeRooms = 0;

    const roomStats: RoomStats[] = [];

    this.rooms.forEach((room) => {
      if (room.is_active) {
        activeRooms++;
        totalViewers += room.viewer_count;
        totalHosts += room.host_peer_id ? 1 : 0;

        roomStats.push({
          room_id: room.room_id,
          post_id: room.post_id,
          host_user_id: room.host_user_id,
          is_active: room.is_active,
          viewer_count: room.viewer_count,
          created_at: room.created_at.toISOString(),
          bytes_sent: 0,
          bytes_received: 0
        });
      }
    });

    return {
      total_rooms: this.rooms.size,
      active_rooms: activeRooms,
      total_peers: this.peers.size,
      total_viewers: totalViewers,
      total_hosts: totalHosts,
      total_bytes_sent: 0,
      total_bytes_received: 0,
      rooms: roomStats
    };
  }

  /**
   * Cleanup idle rooms
   */
  cleanupIdleRooms(idleTimeoutSeconds: number): void {
    const now = Date.now();
    const timeoutMs = idleTimeoutSeconds * 1000;

    const roomsToDelete: string[] = [];

    this.rooms.forEach((room, roomId) => {
      const idleTime = now - room.created_at.getTime();

      // Delete if no host or idle for too long with no viewers
      if (!room.host_peer_id || (room.viewer_count === 0 && idleTime > timeoutMs)) {
        roomsToDelete.push(roomId);
      }
    });

    for (const roomId of roomsToDelete) {
      console.log(`Cleaning up idle room: ${roomId}`);
      this.deleteRoom(roomId);
    }
  }

  /**
   * Get bytes sent for a room from mediasoup stats
   */
  private async getRoomBytesSent(room: Room): Promise<number> {
    let totalBytes = 0;
    try {
      if (room.router) {
        // Aggregate stats from all transports in the room
        this.peers.forEach((peer) => {
          if (peer.room_id === room.room_id) {
            peer.producers.forEach((producer) => {
              // mediasoup stats are async, approximating for now
              totalBytes += 0; // Would need to call producer.getStats()
            });
          }
        });
      }
    } catch (error) {
      console.error('Error getting room bytes sent:', error);
    }
    return totalBytes;
  }

  /**
   * Get bytes received for a room from mediasoup stats
   */
  private async getRoomBytesReceived(room: Room): Promise<number> {
    let totalBytes = 0;
    try {
      if (room.router) {
        this.peers.forEach((peer) => {
          if (peer.room_id === room.room_id) {
            peer.consumers.forEach((consumer) => {
              // Would need to call consumer.getStats()
              totalBytes += 0;
            });
          }
        });
      }
    } catch (error) {
      console.error('Error getting room bytes received:', error);
    }
    return totalBytes;
  }
}

export default RoomManager;
