-- Link posts to places table for place-specific feeds
-- Run this migration after add_places_and_google_pics.sql

-- Add place_id column to posts table
ALTER TABLE posts ADD COLUMN IF NOT EXISTS place_id INTEGER REFERENCES places(id) ON DELETE SET NULL;

-- Add post_count column to places table
ALTER TABLE places ADD COLUMN IF NOT EXISTS post_count INTEGER DEFAULT 0 NOT NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_posts_place_id ON posts(place_id);
CREATE INDEX IF NOT EXISTS idx_posts_google_place_id ON posts(google_place_id);
CREATE INDEX IF NOT EXISTS idx_places_post_count ON places(post_count DESC);
