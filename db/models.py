from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    apple_user_id = Column(String(255), unique=True, index=True, nullable=False)

    # Profile fields
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    nickname = Column(String(50), nullable=True, index=True)
    employer = Column(String(200), nullable=True)
    phone = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    profile_picture = Column(String, nullable=True)
    instagram_handle = Column(String(30), nullable=True, index=True)

    # Privacy settings for Art Basel Miami access control
    phone_visible = Column(Boolean, default=False, nullable=False)
    email_visible = Column(Boolean, default=False, nullable=False)

    # Geolocation tracking for canPost (Art Basel Miami attendees)
    can_post = Column(Boolean, default=False, nullable=False)
    last_location_lat = Column(Float, nullable=True)
    last_location_lon = Column(Float, nullable=True)
    last_location_update = Column(DateTime(timezone=True), nullable=True)

    # QR Code token for mutual connections
    qr_token = Column(String(64), unique=True, index=True, nullable=True)

    # Social handles
    instagram_handle = Column(String(30), nullable=True)
    instagram_profile_pic = Column(Text, nullable=True)
    linkedin_handle = Column(String(100), nullable=True)

    # Legacy fields
    username = Column(String(50), nullable=True)
    bio = Column(String(500), nullable=True)
    refresh_token = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
    check_ins = relationship("CheckIn", back_populates="user", cascade="all, delete-orphan")
    livestreams = relationship("Livestream", back_populates="user", cascade="all, delete-orphan")
    followers = relationship("Follow", foreign_keys="Follow.following_id", back_populates="following", cascade="all, delete-orphan")
    following = relationship("Follow", foreign_keys="Follow.follower_id", back_populates="follower", cascade="all, delete-orphan")
    bounces_created = relationship("Bounce", back_populates="creator", cascade="all, delete-orphan")
    bounce_invites = relationship("BounceInvite", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_profile(self) -> bool:
        """Check if user has completed profile setup"""
        return bool(self.first_name and self.last_name and self.nickname)


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)
    content = Column(Text, nullable=False)
    media_url = Column(String, nullable=True)
    media_type = Column(String(10), nullable=True)  # 'image', 'video', None for text
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    venue_name = Column(String(255), nullable=True)  # Venue name from MapKit (e.g., "Hooters Miami")
    google_place_id = Column(String(255), nullable=True, index=True)  # Google Places ID for venue
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user = relationship("User", back_populates="posts")
    place = relationship("Place", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")


class CheckIn(Base):
    __tablename__ = "check_ins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    user = relationship("User", back_populates="check_ins")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(500), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", backref="user_likes")
    post = relationship("Post", back_populates="likes")


class AnonymousLocation(Base):
    __tablename__ = "anonymous_locations"

    location_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class Livestream(Base):
    __tablename__ = "livestreams"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(String(255), unique=True, index=True, nullable=False)
    post_id = Column(String(255), nullable=True)  # Optional link to a post

    # Stream timing
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Stream status: 'active', 'ended', 'error'
    status = Column(String(20), default='active', nullable=False, index=True)

    # Viewer statistics
    max_viewers = Column(Integer, default=0, nullable=False)
    total_viewers = Column(Integer, default=0, nullable=False)  # Unique viewers

    # Stream metadata
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="livestreams")

    @property
    def duration_seconds(self):
        """Calculate stream duration in seconds"""
        if self.ended_at:
            return int((self.ended_at - self.started_at).total_seconds())
        return None


class Bounce(Base):
    """A location-based event/meetup invitation - 'this is where the party's at'"""
    __tablename__ = "bounces"

    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)

    # Location (kept for backwards compatibility and quick access)
    venue_name = Column(String(255), nullable=False)
    venue_address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    google_place_id = Column(String(255), nullable=True, index=True)  # Google's place_id for linking

    # Timing
    bounce_time = Column(DateTime(timezone=True), nullable=False)
    is_now = Column(Boolean, default=False, nullable=False)

    # Visibility
    is_public = Column(Boolean, default=False, nullable=False)

    # Status: 'active', 'archived'
    status = Column(String(20), default='active', nullable=False, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    creator = relationship("User", back_populates="bounces_created")
    place = relationship("Place", back_populates="bounces")
    invites = relationship("BounceInvite", back_populates="bounce", cascade="all, delete-orphan")
    attendees = relationship("BounceAttendee", back_populates="bounce", cascade="all, delete-orphan")


class BounceInvite(Base):
    """Invitation to a bounce for a specific user"""
    __tablename__ = "bounce_invites"

    id = Column(Integer, primary_key=True, index=True)
    bounce_id = Column(Integer, ForeignKey("bounces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    bounce = relationship("Bounce", back_populates="invites")
    user = relationship("User", back_populates="bounce_invites")


class BounceAttendee(Base):
    """
    Tracks users currently at a bounce location.
    Updated when users are within proximity of an active public bounce.
    Entries expire after 15 minutes of no updates.
    """
    __tablename__ = "bounce_attendees"

    id = Column(Integer, primary_key=True, index=True)
    bounce_id = Column(Integer, ForeignKey("bounces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    bounce = relationship("Bounce", back_populates="attendees")
    user = relationship("User")


class Place(Base):
    """
    Stores Google Places data to avoid duplicate API calls.
    When a bounce or post is created, the place is stored/linked here.
    """
    __tablename__ = "places"

    id = Column(Integer, primary_key=True, index=True)
    google_place_id = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    types = Column(Text, nullable=True)  # JSON array of place types
    bounce_count = Column(Integer, default=0, nullable=False)  # Incremented when new bounces reference this place
    post_count = Column(Integer, default=0, nullable=False)  # Incremented when new posts reference this place
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    photos = relationship("GooglePic", back_populates="place", cascade="all, delete-orphan")
    bounces = relationship("Bounce", back_populates="place")
    posts = relationship("Post", back_populates="place")


class GooglePic(Base):
    """
    Stores Google Places photos for a place.
    Up to 5 photos per place.
    """
    __tablename__ = "google_pics"

    id = Column(Integer, primary_key=True, index=True)
    place_id = Column(Integer, ForeignKey("places.id", ondelete="CASCADE"), nullable=False, index=True)
    photo_reference = Column(String(500), nullable=False)  # Google photo reference
    photo_url = Column(Text, nullable=True)  # Cached photo URL (optional)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    attributions = Column(Text, nullable=True)  # JSON array of attributions
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    place = relationship("Place", back_populates="photos")
