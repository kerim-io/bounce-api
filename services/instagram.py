"""Instagram profile scraping service."""

import re
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

INSTAGRAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
}


@dataclass
class InstagramProfile:
    handle: str
    profile_pic_url: Optional[str] = None
    full_name: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.profile_pic_url is not None


async def fetch_instagram_profile(handle: str) -> InstagramProfile:
    """
    Fetch Instagram profile pic URL for a given handle.

    Tries multiple methods:
    1. Instagram's web API endpoint
    2. Scraping the profile page HTML
    """
    handle = handle.lstrip("@").strip()
    if not handle:
        return InstagramProfile(handle=handle)

    profile_pic_url = None
    full_name = None

    try:
        async with httpx.AsyncClient() as client:
            # Method 1: Try the web profile info endpoint
            response = await client.get(
                f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}",
                headers=INSTAGRAM_HEADERS,
                timeout=10.0
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    user_data = data.get("data", {}).get("user", {})
                    profile_pic_url = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
                    full_name = user_data.get("full_name")
                    if profile_pic_url:
                        logger.info(f"Instagram API success for {handle}")
                except Exception as e:
                    logger.warning(f"Instagram API parse error for {handle}: {e}")
            else:
                logger.warning(f"Instagram API returned {response.status_code} for {handle}")

            # Method 2: Fallback to scraping profile page
            if not profile_pic_url:
                response = await client.get(
                    f"https://www.instagram.com/{handle}/",
                    headers={
                        "User-Agent": INSTAGRAM_HEADERS["User-Agent"],
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Cookie": "ig_cb=1",
                    },
                    follow_redirects=False,
                    timeout=10.0
                )

                if response.status_code != 200:
                    logger.warning(f"Instagram HTML scrape returned {response.status_code} for {handle}")
                if response.status_code == 200:
                    html = response.text

                    # Try to find profile_pic_url_hd in JSON data
                    match = re.search(r'"profile_pic_url_hd":"([^"]+)"', html)
                    if match:
                        profile_pic_url = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                    else:
                        # Try profile_pic_url
                        match = re.search(r'"profile_pic_url":"([^"]+)"', html)
                        if match:
                            profile_pic_url = match.group(1).replace("\\u0026", "&").replace("\\/", "/")
                        else:
                            # Fallback: og:image meta tag
                            match = re.search(r'property="og:image"\s+content="([^"]+)"', html)
                            if match:
                                profile_pic_url = match.group(1)

                    # Try to get full name
                    if not full_name:
                        match = re.search(r'"full_name":"([^"]*)"', html)
                        if match:
                            full_name = match.group(1)

    except Exception as e:
        logger.warning(f"Instagram lookup error for {handle}: {e}")

    return InstagramProfile(
        handle=handle,
        profile_pic_url=profile_pic_url,
        full_name=full_name
    )
