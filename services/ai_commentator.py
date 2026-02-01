import asyncio
import time
import logging
from collections import deque
from math import radians, sin, cos, sqrt, atan2
from typing import Optional, Callable, Awaitable

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in metres between two lat/lng points."""
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


class BounceCommentator:
    """Per-bounce AI commentator that generates witty colour commentary."""

    def __init__(self, bounce_id: int, context: dict):
        self.bounce_id = bounce_id
        self.context = context  # venue_name, venue_address, lat, lng, message, creator_name
        self.attendees: dict[str, dict] = {}  # id -> {name, last_lat, last_lng, last_seen}
        self.chat_buffer: deque = deque(maxlen=50)
        self.last_ai_time: float = 0
        self.min_interval: float = 30.0
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        self._send: Optional[Callable] = None

    def start(self, send_callback: Callable[[int, dict], Awaitable]):
        self._send = send_callback
        self._task = asyncio.create_task(self._process_loop())

    async def stop(self):
        self._stopped = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def push_event(self, event: dict):
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def add_chat(self, sender: str, text: str, is_ai: bool = False):
        self.chat_buffer.append({
            "sender": sender,
            "text": text,
            "is_ai": is_ai,
            "timestamp": time.time(),
        })

    def get_history(self) -> list:
        return list(self.chat_buffer)

    # -- internals --

    async def _process_loop(self):
        while not self._stopped:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=120)
            except asyncio.TimeoutError:
                if self.attendees:
                    event = {"type": "inactivity_check"}
                else:
                    continue
            except asyncio.CancelledError:
                break

            if not settings.ANTHROPIC_API_KEY:
                continue

            now = time.time()
            if now - self.last_ai_time < self.min_interval:
                continue

            if not self._should_comment(event):
                continue

            try:
                commentary = await self._generate(event)
                if commentary:
                    self.last_ai_time = time.time()
                    self.add_chat("Bounce AI", commentary, is_ai=True)
                    await self._send(self.bounce_id, {
                        "type": "chat_message",
                        "sender": "Bounce AI",
                        "text": commentary,
                        "is_ai": True,
                        "timestamp": self.last_ai_time,
                    })
            except Exception as e:
                logger.error(f"AI commentary error for bounce {self.bounce_id}: {e}")

    def _should_comment(self, event: dict) -> bool:
        t = event.get("type")
        if t in ("join", "leave", "chat"):
            return True
        if t == "inactivity_check":
            return time.time() - self.last_ai_time > 120
        if t == "location_update":
            return event.get("arrived_at_venue", False)
        return False

    async def _generate(self, event: dict) -> Optional[str]:
        system = self._system_prompt()
        user = self._event_prompt(event)

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-5-haiku-latest",
                    "max_tokens": 150,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
            if resp.status_code != 200:
                logger.warning(f"Anthropic API {resp.status_code}: {resp.text[:200]}")
                return None
            return resp.json()["content"][0]["text"].strip()

    def _system_prompt(self) -> str:
        names = [a["name"] for a in self.attendees.values()]
        venue = self.context.get("venue_name", "the venue")
        addr = self.context.get("venue_address", "")
        msg = self.context.get("message", "")
        host = self.context.get("creator_name", "the host")

        parts = [
            "You are a witty, warm running commentator for a live group meetup called a Bounce.",
            f"The venue is {venue}" + (f" at {addr}" if addr else "") + ".",
            f"Host: {host}.",
        ]
        if msg:
            parts.append(f'Host says: "{msg}".')
        attendee_str = ", ".join(names) if names else "none yet"
        parts.append(f"Current attendees: {attendee_str}.")
        parts.append(
            "Keep responses to 1-2 short sentences max. Be fun, dry, witty — like a sports "
            "commentator providing colour on a night out. Not every message needs a reply. "
            "No emojis. No hashtags. Refer to people by name."
        )
        return " ".join(parts)

    def _event_prompt(self, event: dict) -> str:
        recent = [f"{m['sender']}: {m['text']}" for m in list(self.chat_buffer)[-8:]]
        ctx = "\nRecent chat:\n" + "\n".join(recent) if recent else ""

        t = event.get("type")
        if t == "join":
            count = len(self.attendees)
            return f"{event['name']} just joined the bounce. There are now {count} people.{ctx}"
        if t == "leave":
            return f"{event['name']} left the bounce.{ctx}"
        if t == "chat":
            return f"{event['sender']} said: \"{event['text']}\"{ctx}"
        if t == "inactivity_check":
            dists = []
            for a in self.attendees.values():
                if a.get("last_lat"):
                    d = _haversine(a["last_lat"], a["last_lng"],
                                   self.context["latitude"], self.context["longitude"])
                    dists.append(f"{a['name']} is {int(d)}m away")
            dist_info = ". ".join(dists) if dists else "No location data"
            return f"It's been quiet. {dist_info}.{ctx}"
        if t == "location_update":
            return f"{event['name']} just arrived at the venue!{ctx}"
        return f"Something happened in the bounce.{ctx}"

    def check_arrival(self, attendee_id: str, name: str, lat: float, lng: float):
        """Check if attendee crossed from >100m to <=50m of venue. Push event if so."""
        prev = self.attendees.get(attendee_id, {})
        prev_dist = (_haversine(prev["last_lat"], prev["last_lng"],
                                self.context["latitude"], self.context["longitude"])
                     if prev.get("last_lat") else 9999)
        new_dist = _haversine(lat, lng, self.context["latitude"], self.context["longitude"])

        self.attendees[attendee_id] = {
            "name": name, "last_lat": lat, "last_lng": lng, "last_seen": time.time()
        }

        if prev_dist > 100 and new_dist <= 50:
            self.push_event({"type": "location_update", "name": name, "arrived_at_venue": True})


# Global registry
_commentators: dict[int, BounceCommentator] = {}


def get_or_create_commentator(
    bounce_id: int, context: dict, send_callback: Callable
) -> BounceCommentator:
    if bounce_id not in _commentators:
        c = BounceCommentator(bounce_id, context)
        c.start(send_callback)
        _commentators[bounce_id] = c
    return _commentators[bounce_id]


async def remove_commentator(bounce_id: int):
    if bounce_id in _commentators:
        await _commentators[bounce_id].stop()
        del _commentators[bounce_id]
