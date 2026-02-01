-- Add is_connected column to bounce_guest_locations
-- Tracks whether a guest is currently connected via WebSocket (separate from location sharing)
ALTER TABLE bounce_guest_locations ADD COLUMN IF NOT EXISTS is_connected BOOLEAN NOT NULL DEFAULT false;
