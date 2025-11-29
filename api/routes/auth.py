from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from db.database import get_async_session
from db.models import User, RefreshToken
from services.auth_service import create_access_token, create_refresh_token, decode_token
from services.apple_auth import verify_apple_token
from core.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])

PASSCODE = "ARTBASEL2024"


class AppleAuthRequest(BaseModel):
    code: str
    redirect_uri: str
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    email: Optional[str] = None  # Email from iOS (Apple only sends on first auth)


class PasscodeAuthRequest(BaseModel):
    passcode: str
    username: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str
    user_id: int
    email: Optional[str]
    has_profile: bool


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/apple", response_model=AuthResponse)
async def apple_signin(
    request: AppleAuthRequest,
    db: AsyncSession = Depends(get_async_session)
):
    """Sign in with Apple - validates code with Apple servers"""
    # Log what we received from iOS
    print(f"📱 Apple Auth Request:")
    print(f"   given_name: {request.given_name}")
    print(f"   family_name: {request.family_name}")
    print(f"   email: {request.email}")

    try:
        # Verify Apple token
        apple_data = await verify_apple_token(request.code, request.redirect_uri)
        apple_user_id = apple_data["user_id"]
        # Prefer email from iOS request (Apple sends it), fallback to token email
        email = request.email or apple_data.get("email")

        # Check if user exists
        result = await db.execute(
            select(User).where(User.apple_user_id == apple_user_id)
        )
        user = result.scalar_one_or_none()

        # Create user if doesn't exist
        if not user:
            user = User(
                apple_user_id=apple_user_id,
                email=email,
                username=email.split("@")[0] if email else f"user_{apple_user_id[:8]}",
                first_name=request.given_name,
                last_name=request.family_name,
                is_active=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # Update existing user with name if provided and not already set
            updated = False
            if request.given_name and not user.first_name:
                user.first_name = request.given_name
                updated = True
            if request.family_name and not user.last_name:
                user.last_name = request.family_name
                updated = True
            if request.email and not user.email:
                user.email = request.email
                updated = True
            if updated:
                await db.commit()
                await db.refresh(user)

        # Create tokens
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token_str = create_refresh_token({"sub": str(user.id)})

        # Store refresh token
        refresh_token_obj = RefreshToken(
            user_id=user.id,
            token=refresh_token_str,
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
        db.add(refresh_token_obj)

        # Update user's Apple refresh token
        user.refresh_token = apple_data.get("refresh_token")
        await db.commit()

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token_str,
            token_type="bearer",
            user_id=user.id,
            email=user.email,
            has_profile=user.has_profile
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Apple authentication failed: {str(e)}"
        )


@router.post("/passcode", response_model=AuthResponse)
async def passcode_auth(
    request: PasscodeAuthRequest,
    db: AsyncSession = Depends(get_async_session)
):
    """Auth with passcode fallback (ARTBASEL2024)"""
    if request.passcode != PASSCODE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid passcode"
        )

    # Create/get guest user
    username = request.username or f"guest_{datetime.utcnow().timestamp()}"
    guest_id = f"passcode_{username}"

    result = await db.execute(
        select(User).where(User.apple_user_id == guest_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            apple_user_id=guest_id,
            username=username,
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Create tokens
    access_token = create_access_token({"sub": str(user.id)})

    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        has_profile=user.has_profile
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token_endpoint(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_async_session)
):
    """
    Refresh access token using refresh_token.

    iOS should call this when access_token expires (401 error).
    """
    try:
        # Verify refresh token is valid and not expired
        payload = decode_token(request.refresh_token)
        user_id = int(payload.get("sub"))

        # Check if refresh token exists in database and isn't expired
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token == request.refresh_token,
                RefreshToken.user_id == user_id,
                RefreshToken.expires_at > datetime.utcnow()
            )
        )
        refresh_token_obj = result.scalar_one_or_none()

        if not refresh_token_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )

        # Get user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create new access token (keep same refresh token)
        access_token = create_access_token({"sub": str(user.id)})

        return AuthResponse(
            access_token=access_token,
            refresh_token=request.refresh_token,  # Return same refresh token
            token_type="bearer",
            user_id=user.id,
            email=user.email,
            has_profile=user.has_profile
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token refresh failed: {str(e)}"
        )
