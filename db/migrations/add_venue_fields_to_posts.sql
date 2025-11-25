-- Add venue/location fields to posts table for Apple MapKit location picker feature
-- Allows posts to be tagged with venues (e.g., "Hooters Miami")

ALTER TABLE posts ADD COLUMN venue_name VARCHAR(255) NULL;
ALTER TABLE posts ADD COLUMN venue_id VARCHAR(255) NULL;

-- Add helpful comments
COMMENT ON COLUMN posts.venue_name IS 'Venue name from Apple MapKit search (e.g., "Hooters Miami")';
COMMENT ON COLUMN posts.venue_id IS 'Venue identifier, typically lat,lon coordinates (e.g., "25.123,-80.456")';
