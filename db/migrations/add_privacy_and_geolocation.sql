-- Migration: Add privacy and geolocation fields to User model
-- Date: 2025-11-23
-- Description: Add phone_visible, email_visible, can_post, and location tracking fields

-- Add privacy settings columns
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_visible BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_visible BOOLEAN NOT NULL DEFAULT FALSE;

-- Add geolocation tracking columns for Art Basel Miami access control
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_post BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_location_lat DOUBLE PRECISION;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_location_lon DOUBLE PRECISION;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_location_update TIMESTAMP WITH TIME ZONE;

-- Create index on can_post for faster queries
CREATE INDEX IF NOT EXISTS idx_users_can_post ON users(can_post);
CREATE INDEX IF NOT EXISTS idx_users_last_location_update ON users(last_location_update);
