-- Migration: Add venue check-in support to check_ins table
-- Date: 2025-11-29
-- Description: Extend check_ins to support venue-based check-ins with Google Place ID

-- Add new columns to check_ins table
ALTER TABLE check_ins
ADD COLUMN IF NOT EXISTS google_place_id VARCHAR(255),
ADD COLUMN IF NOT EXISTS place_id INTEGER REFERENCES places(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_checkins_google_place_id ON check_ins(google_place_id);
CREATE INDEX IF NOT EXISTS idx_checkins_place_id ON check_ins(place_id);
CREATE INDEX IF NOT EXISTS idx_checkins_last_seen ON check_ins(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_checkins_active ON check_ins(is_active) WHERE is_active = TRUE;

-- Composite index for venue check-in queries (active check-ins at a place)
CREATE INDEX IF NOT EXISTS idx_checkins_venue_active
ON check_ins(google_place_id, last_seen_at)
WHERE is_active = TRUE;
