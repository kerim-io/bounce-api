-- Add instagram_handle column to users table for social media search
ALTER TABLE users ADD COLUMN IF NOT EXISTS instagram_handle VARCHAR(30);
CREATE INDEX IF NOT EXISTS idx_users_instagram_handle ON users(instagram_handle);

-- Add index on nickname for efficient search (if not exists)
CREATE INDEX IF NOT EXISTS idx_users_nickname ON users(nickname);
