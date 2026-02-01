from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, ForeignKey, Text, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base
import uuid
import enum


class CloseFriendStatus(str, enum.Enum):
    """Status of close friend relationship"""
    NONE = "none"
    PENDING = "pending"
    ACCEPTED = "accepted"


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
    profile_picture = Column(String, nullable=True)  # Legacy - kept for backwards compatibility
    profile_picture_1 = Column(Text, nullable=True)  # Base64 encoded image
    profile_picture_2 = Column(Text, nullable=True)  # Base64 encoded image
    profile_picture_3 = Column(Text, nullable=True)  # Base64 encoded image
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
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    check_ins = relationship("CheckIn", back_populates="user", cascade="all, delete-orphan")
    followers = relationship("Follow", foreign_keys="Follow.following_id", back_populates="following", cascade="all, delete-orphan")
    following = relationship("Follow", foreign_keys="Follow.follower_id", back_populates="follower", cascade="all, delete-orphan")
    bounces_created = relationship("Bounce", back_populates="creator", cascade="all, delete-orphan")
    bounce_invites = relationship("BounceInvite", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_profile(self) -> bool:
        """Check if user has completed profile setup (nickname required)"""
        return bool(self.nickname)


class Follow(Base):
    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_close_friend = Column(Boolean, default=False, nullable=False)  # Legacy - keeping for backwards compatibility
    close_friend_status = Column(SQLEnum('none', 'pending', 'accepted', name='close_friend_status', create_type=False), default='none', nullable=False)
    close_friend_requester_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_sharing_location = Column(Boolean, default=False, nullable=False)  # Whether this user shares location with the followed user
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers")
    close_friend_requester = relationship("User", foreign_keys=[close_friend_requester_id])


class DeviceToken(Base):
    """Store APNs device tokens for push notifications"""
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_token = Column(String(255), nullable=False)
    device_name = Column(String(100), nullable=True)
    platform = Column(String(20), default='ios')
    is_sandbox = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, index=True)

    user = relationship("User", backref="device_tokens", passive_deletes=True)

    __table_args__ = (
        UniqueConstraint('user_id', 'device_token', name='uq_user_device_token'),
    )


class NotificationPreference(Base):
    """User notification preferences for push notifications"""
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    bounce_invites = Column(Boolean, default=True)
    new_followers = Column(Boolean, default=True)
    follow_backs = Column(Boolean, default=True)
    friends_at_same_venue = Column(Boolean, default=True)
    friends_leaving_venue = Column(Boolean, default=True)
    close_friend_checkins = Column(Boolean, default=True)
    push_enabled = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", backref="notification_preferences", passive_deletes=True)


class CheckIn(Base):
    __tablename__ = "check_ins"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    location_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Venue check-in fields (Google Places integration)
    place_id = Column(String(255), nullable=True, index=True)  # Google Places ID
    places_fk_id = Column(Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships
    user = relationship("User", back_populates="check_ins")
    place = relationship("Place", back_populates="check_ins", foreign_keys=[places_fk_id])


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(500), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AnonymousLocation(Base):
    __tablename__ = "anonymous_locations"

    location_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class Bounce(Base):
    """A location-based event/meetup invitation - 'this is where the party's at'"""
    __tablename__ = "bounces"

    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    places_fk_id = Column(Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)

    # Location (kept for backwards compatibility and quick access)
    venue_name = Column(String(255), nullable=False)
    venue_address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    place_id = Column(String(255), nullable=True, index=True)  # Google's place_id for linking

    # Timing
    bounce_time = Column(DateTime(timezone=True), nullable=False)
    is_now = Column(Boolean, default=False, nullable=False)

    # Visibility
    is_public = Column(Boolean, default=False, nullable=False)

    # Creator message (optional hype text like "The Hart, time to hunt")
    message = Column(String(500), nullable=True)

    # Status: 'active', 'archived'
    status = Column(String(20), default='active', nullable=False, index=True)

    # Share link token for web map
    share_token = Column(String(64), unique=True, index=True, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationships
    creator = relationship("User", back_populates="bounces_created")
    place = relationship("Place", back_populates="bounces", foreign_keys=[places_fk_id])
    invites = relationship("BounceInvite", back_populates="bounce", cascade="all, delete-orphan")
    attendees = relationship("BounceAttendee", back_populates="bounce", cascade="all, delete-orphan")


class BounceInvite(Base):
    """Invitation to a bounce for a specific user"""
    __tablename__ = "bounce_invites"

    id = Column(Integer, primary_key=True, index=True)
    bounce_id = Column(Integer, ForeignKey("bounces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default='pending', nullable=False)  # pending, accepted, declined
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


class BounceLocationShare(Base):
    """
    Tracks real-time location sharing for bounce attendees.
    Users can opt-in to share their live location with other bounce participants.
    """
    __tablename__ = "bounce_location_shares"

    id = Column(Integer, primary_key=True, index=True)
    bounce_id = Column(Integer, ForeignKey("bounces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    is_sharing = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)

    # Relationships
    bounce = relationship("Bounce")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('bounce_id', 'user_id', name='uq_bounce_user_location'),
    )


class Place(Base):
    """
    Stores Google Places data to avoid duplicate API calls.
    When a bounce or post is created, the place is stored/linked here.
    """
    __tablename__ = "places"

    id = Column(Integer, primary_key=True, index=True)
    place_id = Column(String(255), unique=True, index=True, nullable=False)  # Google Places ID
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    types = Column(Text, nullable=True)  # JSON array of place types
    bounce_count = Column(Integer, default=0, nullable=False)  # Incremented when new bounces reference this place
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    photos = relationship("GooglePic", back_populates="place", cascade="all, delete-orphan")
    bounces = relationship("Bounce", back_populates="place")
    check_ins = relationship("CheckIn", back_populates="place")


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


class CheckInHistory(Base):
    """
    Permanent record of all user check-ins at venues.
    Query by user_id for user's check-in history.
    Query by place_id for venue's check-in history.
    """
    __tablename__ = "check_in_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    place_id = Column(String(255), nullable=False, index=True)  # Google Places ID
    places_fk_id = Column(Integer, ForeignKey("places.id", ondelete="SET NULL"), nullable=True, index=True)

    # Denormalized venue info for historical record
    venue_name = Column(String(255), nullable=False)
    venue_address = Column(String(500), nullable=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Timestamps
    checked_in_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    checked_out_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    place = relationship("Place")


class BounceGuestLocation(Base):
    """Tracks guest (non-app user) locations shared via bounce share link"""
    __tablename__ = "bounce_guest_locations"

    id = Column(Integer, primary_key=True, index=True)
    bounce_id = Column(Integer, ForeignKey("bounces.id", ondelete="CASCADE"), nullable=False, index=True)
    guest_id = Column(String(64), nullable=False)       # browser sessionStorage UUID
    display_name = Column(String(100), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    is_sharing = Column(Boolean, default=True, nullable=False)
    is_connected = Column(Boolean, default=False, nullable=False, server_default="false")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    bounce = relationship("Bounce")

    __table_args__ = (
        UniqueConstraint('bounce_id', 'guest_id', name='uq_bounce_guest_location'),
    )
