-- Add qr_token column to users table for QR code mutual connections
ALTER TABLE users ADD COLUMN IF NOT EXISTS qr_token VARCHAR(64) UNIQUE;
CREATE INDEX IF NOT EXISTS idx_users_qr_token ON users(qr_token);
