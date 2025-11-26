-- Bounces feature: Event meetups at venues
-- Run this migration to add bounces and bounce_invites tables

-- Bounces table
CREATE TABLE IF NOT EXISTS bounces (
    id SERIAL PRIMARY KEY,
    creator_id INTEGER REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    venue_name VARCHAR(255) NOT NULL,
    venue_address VARCHAR(500),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    bounce_time TIMESTAMP WITH TIME ZONE NOT NULL,
    is_now BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT TRUE,
    status VARCHAR(50) DEFAULT 'active',  -- active, cancelled, completed
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Bounce invites table
CREATE TABLE IF NOT EXISTS bounce_invites (
    id SERIAL PRIMARY KEY,
    bounce_id INTEGER REFERENCES bounces(id) ON DELETE CASCADE NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, accepted, declined
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(bounce_id, user_id)
);

-- Indexes for bounces
CREATE INDEX IF NOT EXISTS idx_bounces_creator ON bounces(creator_id);
CREATE INDEX IF NOT EXISTS idx_bounces_status ON bounces(status);
CREATE INDEX IF NOT EXISTS idx_bounces_public ON bounces(is_public, status, bounce_time);
CREATE INDEX IF NOT EXISTS idx_bounces_location ON bounces(latitude, longitude);

-- Indexes for bounce_invites
CREATE INDEX IF NOT EXISTS idx_bounce_invites_user ON bounce_invites(user_id);
CREATE INDEX IF NOT EXISTS idx_bounce_invites_bounce ON bounce_invites(bounce_id);
