"""Instagram 2FA Verification Service

This module provides Instagram account verification via DM codes.
It's designed to be integrated with the main app but well-separated
for potential future extraction as a standalone service.

Key abstraction: Any service can plug in (ig_handle, client_id, callback_data)
to verify an Instagram account.

Usage:
    from services.instagram_2fa import (
        request_verification,
        confirm_code,
        get_verification,
        cancel_verification,
        start_ig_poller,
        stop_ig_poller,
    )
"""

from .service import (
    request_verification,
    confirm_code,
    get_verification,
    cancel_verification,
    get_user_id_by_handle,
    normalize_handle,
)

from .poller import (
    start_ig_poller,
    stop_ig_poller,
)

from .models import (
    PendingVerification,
    VerificationStatus,
    VerificationRequest,
    VerificationConfirm,
    VerificationStatusResponse,
    VerificationRequestResponse,
)

__all__ = [
    # Service functions
    "request_verification",
    "confirm_code",
    "get_verification",
    "cancel_verification",
    "get_user_id_by_handle",
    "normalize_handle",
    # Poller
    "start_ig_poller",
    "stop_ig_poller",
    # Models
    "PendingVerification",
    "VerificationStatus",
    "VerificationRequest",
    "VerificationConfirm",
    "VerificationStatusResponse",
    "VerificationRequestResponse",
]
