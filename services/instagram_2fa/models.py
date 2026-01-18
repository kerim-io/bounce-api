"""Pydantic models for Instagram 2FA verification"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class VerificationStatus(str, Enum):
    PENDING = "pending"
    CODE_SENT = "code_sent"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class PendingVerification(BaseModel):
    """Data stored in Redis for a pending verification"""
    client_id: str = "litapp"  # Service identifier for future multi-client support
    user_id: int
    instagram_handle: str  # Normalized (lowercase, no @)
    verification_code: str  # 6-digit code
    status: VerificationStatus = VerificationStatus.PENDING
    created_at: datetime
    dm_sent_at: Optional[datetime] = None
    callback_url: Optional[str] = None  # For external services (future)


# API Request/Response models

class VerificationRequest(BaseModel):
    """Request to start Instagram verification"""
    instagram_handle: str = Field(..., min_length=1, max_length=30)


class VerificationConfirm(BaseModel):
    """Request to confirm verification code"""
    code: str = Field(..., min_length=6, max_length=6)


class VerificationStatusResponse(BaseModel):
    """Response with current verification status"""
    status: VerificationStatus
    instagram_handle: str
    message: str
    dm_sent_at: Optional[datetime] = None


class VerificationRequestResponse(BaseModel):
    """Response after requesting verification"""
    status: VerificationStatus
    instagram_handle: str
    message: str
    instructions: str
