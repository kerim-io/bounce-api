"""API endpoints for Instagram 2FA verification"""

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_async_session
from db.models import User
from api.dependencies import get_current_user, limiter
from services.instagram_2fa import (
    request_verification,
    confirm_code,
    get_verification,
    cancel_verification,
    VerificationRequest,
    VerificationConfirm,
    VerificationStatusResponse,
    VerificationRequestResponse,
    VerificationStatus,
)

router = APIRouter(prefix="/instagram/verify", tags=["instagram"])


@router.post("/request", response_model=VerificationRequestResponse)
@limiter.limit("5/minute")
async def request_instagram_verification(
    request: Request,
    body: VerificationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Start Instagram verification process.

    1. User claims their Instagram handle
    2. A pending verification is created with a 6-digit code
    3. User should follow @litapp on Instagram
    4. When detected, a DM with the code will be sent
    """
    try:
        verification = await request_verification(
            user_id=current_user.id,
            instagram_handle=body.instagram_handle
        )

        return VerificationRequestResponse(
            status=verification.status,
            instagram_handle=verification.instagram_handle,
            message="Verification started",
            instructions=(
                f"Follow @litapp on Instagram from your account @{verification.instagram_handle}. "
                "You will receive a DM with a 6-digit verification code."
            )
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start verification: {str(e)}"
        )


@router.post("/confirm", response_model=VerificationStatusResponse)
@limiter.limit("10/minute")
async def confirm_instagram_verification(
    request: Request,
    body: VerificationConfirm,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    Confirm Instagram verification with the 6-digit code.

    The code is sent via Instagram DM after following @litapp.
    """
    success, message = await confirm_code(
        user_id=current_user.id,
        code=body.code,
        db=db
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    verification = await get_verification(current_user.id)

    return VerificationStatusResponse(
        status=VerificationStatus.VERIFIED,
        instagram_handle=verification.instagram_handle if verification else "",
        message=message,
        dm_sent_at=verification.dm_sent_at if verification else None
    )


@router.get("/status", response_model=VerificationStatusResponse)
@limiter.limit("30/minute")
async def get_verification_status(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Get current Instagram verification status.

    Possible statuses:
    - pending: Waiting for user to follow @litapp
    - code_sent: DM sent, waiting for code confirmation
    - verified: Verification complete
    - failed: Verification failed
    - expired: Verification request expired
    """
    verification = await get_verification(current_user.id)

    if not verification:
        # Check if user already has a verified Instagram handle
        if current_user.instagram_handle:
            return VerificationStatusResponse(
                status=VerificationStatus.VERIFIED,
                instagram_handle=current_user.instagram_handle,
                message="Instagram already verified"
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending verification found"
        )

    status_messages = {
        VerificationStatus.PENDING: "Waiting for you to follow @litapp on Instagram",
        VerificationStatus.CODE_SENT: "Verification code sent via DM. Check your Instagram messages.",
        VerificationStatus.VERIFIED: "Instagram account verified",
        VerificationStatus.FAILED: "Verification failed",
        VerificationStatus.EXPIRED: "Verification request expired",
    }

    return VerificationStatusResponse(
        status=verification.status,
        instagram_handle=verification.instagram_handle,
        message=status_messages.get(verification.status, "Unknown status"),
        dm_sent_at=verification.dm_sent_at
    )


@router.delete("/cancel")
@limiter.limit("5/minute")
async def cancel_instagram_verification(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    """
    Cancel a pending Instagram verification.

    This removes the pending verification record, allowing the user
    to start a new verification with a different handle if needed.
    """
    success = await cancel_verification(current_user.id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending verification found"
        )

    return {"message": "Verification cancelled"}
