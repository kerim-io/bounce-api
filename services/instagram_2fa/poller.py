"""Background polling task for Instagram follower detection"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from core.config import settings
from .client import get_ig_client
from .service import (
    get_all_pending_handles,
    get_verification,
    update_verification_status,
)
from .models import VerificationStatus

logger = logging.getLogger(__name__)

# Module-level task reference
_poller_task: Optional[asyncio.Task] = None
_running = False


async def _poll_followers():
    """
    Single poll iteration:
    1. Get new followers from Instagram
    2. Match against pending verifications
    3. Send DM with verification code
    """
    ig_client = await get_ig_client()

    # Get all current followers and find new ones
    new_follower_pks = await ig_client.get_new_followers()

    if not new_follower_pks:
        return

    logger.info(f"Found {len(new_follower_pks)} new followers")

    # Get all pending verification handles
    pending_handles = await get_all_pending_handles()
    if not pending_handles:
        return

    # For each new follower, check if their username matches a pending verification
    for pk in new_follower_pks:
        username = await ig_client.get_username_by_pk(pk)
        if not username:
            continue

        # Check if this username has a pending verification
        if username in pending_handles:
            user_id = pending_handles[username]
            verification = await get_verification(user_id)

            if verification and verification.status == VerificationStatus.PENDING:
                # Send DM with verification code
                message = (
                    f"Your Lit App verification code is: {verification.verification_code}\n\n"
                    f"Enter this code in the app to verify your Instagram account."
                )

                success = await ig_client.send_dm(pk, message)

                if success:
                    await update_verification_status(
                        user_id,
                        VerificationStatus.CODE_SENT,
                        dm_sent_at=datetime.now(timezone.utc)
                    )
                    logger.info(f"Verification DM sent to @{username} for user {user_id}")
                else:
                    logger.error(f"Failed to send verification DM to @{username}")


async def _poller_loop():
    """Main polling loop"""
    global _running

    logger.info(f"Instagram poller started (interval: {settings.IG_POLL_INTERVAL}s)")

    while _running:
        try:
            await _poll_followers()
        except Exception as e:
            logger.error(f"Poller error: {e}", exc_info=True)

        await asyncio.sleep(settings.IG_POLL_INTERVAL)

    logger.info("Instagram poller stopped")


async def start_ig_poller():
    """Start the background poller task"""
    global _poller_task, _running

    if not settings.IG_USERNAME or not settings.IG_PASSWORD:
        logger.warning("Instagram credentials not configured, poller not started")
        return

    if _running:
        logger.warning("Instagram poller already running")
        return

    _running = True
    _poller_task = asyncio.create_task(_poller_loop())
    logger.info("Instagram poller task created")


async def stop_ig_poller():
    """Stop the background poller task"""
    global _poller_task, _running

    _running = False

    if _poller_task:
        _poller_task.cancel()
        try:
            await _poller_task
        except asyncio.CancelledError:
            pass
        _poller_task = None

    logger.info("Instagram poller stopped")
