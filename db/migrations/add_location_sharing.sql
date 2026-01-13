-- Add location sharing column to follows table
ALTER TABLE follows ADD COLUMN IF NOT EXISTS is_sharing_location BOOLEAN NOT NULL DEFAULT FALSE;
