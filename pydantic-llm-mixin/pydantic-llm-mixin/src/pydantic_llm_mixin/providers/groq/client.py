"""
Groq API Client

Simplified high-performance Groq client for GenerativeMixin.
Focuses on chat completion with retry logic and rate limiting.
"""

import asyncio
import logging
import time
from typing import Any

import httpx
from pydantic import ValidationError

from .models import (
    GroqChatRequest,
    GroqChatResponse,
    GroqModel,
    ReasoningEffort,
    ReasoningFormat,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter with exponential backoff."""

    def __init__(
        self,
        requests_per_minute: int = 300,
        requests_per_day: int = 144000,
        exponential_base: float = 2.0,
        max_backoff: float = 60.0,
    ):
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests per minute (default: 300 for Groq Dev tier)
            requests_per_day: Maximum requests per day (default: 144000 for Groq Dev tier)
            exponential_base: Base for exponential backoff
            max_backoff: Maximum backoff time in seconds
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day
        self.exponential_base = exponential_base
        self.max_backoff = max_backoff

        # Token buckets
        self.minute_tokens = requests_per_minute
        self.minute_reset_time = time.time() + 60
        self.day_tokens = requests_per_day
        self.day_reset_time = time.time() + 86400

        # Backoff tracking
        self.consecutive_rate_limits = 0
        self.last_rate_limit_time = 0

    def _refill_buckets(self):
        """Refill token buckets if time has elapsed."""
        now = time.time()

        # Refill minute bucket
        if now >= self.minute_reset_time:
            self.minute_tokens = self.requests_per_minute
            self.minute_reset_time = now + 60
            logger.debug(f"Refilled minute bucket to {self.requests_per_minute} tokens")

        # Refill day bucket
        if now >= self.day_reset_time:
            self.day_tokens = self.requests_per_day
            self.day_reset_time = now + 86400
            logger.debug(f"Refilled day bucket to {self.requests_per_day} tokens")

    async def acquire(self) -> float:
        """Acquire permission to make request with exponential backoff.

        Returns:
            Delay in seconds (0 if no delay needed)
        """
        self._refill_buckets()

        # Check if we have tokens
        if self.minute_tokens > 0 and self.day_tokens > 0:
            self.minute_tokens -= 1
            self.day_tokens -= 1
            # Reset backoff on successful acquire
            self.consecutive_rate_limits = 0
            return 0

        # Calculate backoff delay
        delay = min(
            self.exponential_base**self.consecutive_rate_limits,
            self.max_backoff,
        )

        logger.warning(
            f"Rate limit reached. Backing off for {delay:.1f}s "
            f"(attempt {self.consecutive_rate_limits + 1}). "
            f"Tokens: minute={self.minute_tokens}, day={self.day_tokens}"
        )

        self.consecutive_rate_limits += 1
        self.last_rate_limit_time = time.time()

        await asyncio.sleep(delay)

        # Refill after sleep and try again
        self._refill_buckets()

        if self.minute_tokens > 0 and self.day_tokens > 0:
            self.minute_tokens -= 1
            self.day_tokens -= 1
            return delay

        # Still no tokens - return delay for next attempt
        return delay

    def record_rate_limit_error(self):
        """Record that we hit a rate limit error from API."""
        self.consecutive_rate_limits += 1
        self.last_rate_limit_time = time.time()
        logger.warning(f"API rate limit error detected (consecutive: {self.consecutive_rate_limits})")

    def reset_backoff(self):
        """Reset backoff counter after successful request."""
        self.consecutive_rate_limits = 0


class GroqClientError(Exception):
    """Groq client error"""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_type: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(message)


class GroqClient:
    """Simplified Groq API client for GenerativeMixin"""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        api_key: str,
        model_version: str | None = None,
        default_model: GroqModel = GroqModel.OPENAI_GPT_OSS_120B,
        temperature: float = 0.6,
        max_tokens: int = 2048,
        retry_base_delay: float = 1.0,
        generation_max_retries: int = 3,
    ):
        """Initialize Groq client

        Args:
            api_key: Groq API key
            model_version: Groq-Model-Version header value (e.g., "latest", "2025-08-16")
            default_model: Default model to use
            temperature: Default temperature
            max_tokens: Default max tokens
            retry_base_delay: Base delay for retries (seconds)
            generation_max_retries: Max retries for generation
        """
        self.api_key = api_key
        self.model_version = model_version
        self.default_model = default_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_base_delay = retry_base_delay
        self.generation_max_retries = generation_max_retries

        if not self.api_key:
            raise GroqClientError("Groq API key not provided")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Add Groq-Model-Version header if specified
        if self.model_version:
            headers["Groq-Model-Version"] = self.model_version

        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(60.0),
        )

        # Initialize rate limiter
        self.rate_limiter = RateLimiter(
            requests_per_minute=300,
            requests_per_day=144000,
            exponential_base=2.0,
            max_backoff=60.0,
        )

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def close(self):
        """Close the client"""
        try:
            await self.client.aclose()
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                pass
            else:
                raise

    def _validate_model_reasoning_params(
        self,
        model: GroqModel,
        reasoning_format: ReasoningFormat | None,
        reasoning_effort: ReasoningEffort | None,
        include_reasoning: bool | None,
    ) -> dict[str, Any]:
        """Validate and normalize reasoning parameters for specific models"""
        params = {}

        if model in [GroqModel.OPENAI_GPT_OSS_20B, GroqModel.OPENAI_GPT_OSS_120B]:
            # GPT-OSS models don't support reasoning_format
            if reasoning_format:
                logger.warning(f"reasoning_format not supported for {model}, ignoring")

            # GPT-OSS supports include_reasoning and specific effort levels
            if include_reasoning is not None:
                params["include_reasoning"] = include_reasoning

            if reasoning_effort in [
                ReasoningEffort.LOW,
                ReasoningEffort.MEDIUM,
                ReasoningEffort.HIGH,
            ]:
                params["reasoning_effort"] = reasoning_effort.value if reasoning_effort else None
            elif reasoning_effort:
                logger.warning(f"reasoning_effort {reasoning_effort} not supported for {model}")

        else:
            # Non-GPT-OSS models support reasoning_format
            if reasoning_format:
                params["reasoning_format"] = reasoning_format.value

            # Qwen3 32B supports none/default effort levels
            if model == GroqModel.QWEN3_32B:
                if reasoning_effort in [ReasoningEffort.NONE, ReasoningEffort.DEFAULT]:
                    params["reasoning_effort"] = reasoning_effort.value if reasoning_effort else None
                elif reasoning_effort:
                    logger.warning(f"reasoning_effort {reasoning_effort} not supported for {model}")

            if include_reasoning is not None:
                logger.warning(f"include_reasoning not supported for {model}, ignoring")

        return params

    async def chat_completion(self, request: GroqChatRequest) -> GroqChatResponse:
        """Create chat completion with rate limiting and exponential backoff.

        Args:
            request: Chat completion request

        Returns:
            Chat completion response

        Raises:
            GroqClientError: API error occurred
        """
        # Retry up to 5 times with rate limiting and exponential backoff
        max_retries = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                # Acquire rate limit permission (may wait)
                await self.rate_limiter.acquire()

                # Validate reasoning parameters for the model
                reasoning_params = self._validate_model_reasoning_params(
                    request.model,
                    request.reasoning_format,
                    request.reasoning_effort,
                    request.include_reasoning,
                )

                # Build request payload
                payload = request.model_dump(exclude_none=True)
                payload.update(reasoning_params)
                payload["stream"] = False

                response = await self.client.post("/chat/completions", json=payload)

                # Handle rate limit responses
                if response.status_code == 429:
                    self.rate_limiter.record_rate_limit_error()

                    if attempt < max_retries - 1:
                        backoff_delay = min(
                            self.rate_limiter.exponential_base ** (attempt + 1),
                            self.rate_limiter.max_backoff,
                        )
                        logger.warning(
                            f"Rate limit (429) on attempt {attempt + 1}/{max_retries}. "
                            f"Backing off for {backoff_delay:.1f}s"
                        )
                        await asyncio.sleep(backoff_delay)
                        continue

                    raise GroqClientError(
                        "Rate limit exceeded after all retries",
                        status_code=429,
                        error_type="rate_limit_error",
                    )

                if response.status_code != 200:
                    try:
                        error_data = response.json() if response.content else {}
                    except Exception:
                        error_data = {"error": {"message": f"HTTP {response.status_code}: {response.text[:200]}"}}
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")

                    # Retry on the specific tool_choice error
                    if "tool choice is none" in error_msg.lower() and "model called a tool" in error_msg.lower():
                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Groq tool_choice error on attempt {attempt + 1}/{max_retries}, retrying..."
                            )
                            await asyncio.sleep(0.5)
                            continue

                    raise GroqClientError(
                        f"Groq API error: {error_msg}",
                        status_code=response.status_code,
                        error_type=error_data.get("error", {}).get("type"),
                    )

                response_data = response.json()

                # Check for empty response (often indicates rate limiting)
                if not response_data or not response_data.get("choices"):
                    if attempt < max_retries - 1:
                        self.rate_limiter.record_rate_limit_error()
                        backoff_delay = min(
                            self.rate_limiter.exponential_base ** (attempt + 1),
                            self.rate_limiter.max_backoff,
                        )
                        logger.warning(
                            f"Empty response on attempt {attempt + 1}/{max_retries}. "
                            f"Backing off for {backoff_delay:.1f}s"
                        )
                        await asyncio.sleep(backoff_delay)
                        continue

                    raise GroqClientError("No response content received from LLM after all retries")

                # Success - reset backoff
                self.rate_limiter.reset_backoff()
                return GroqChatResponse(**response_data)

            except ValidationError as e:
                logger.error(f"Response validation error: {e}")
                raise GroqClientError(f"Invalid response format: {e}") from e
            except httpx.RequestError as e:
                logger.error(f"Request error: {e}")

                if attempt < max_retries - 1:
                    backoff_delay = min(2.0 ** (attempt + 1), 30.0)
                    logger.warning(
                        f"Network error on attempt {attempt + 1}/{max_retries}. Retrying in {backoff_delay:.1f}s"
                    )
                    await asyncio.sleep(backoff_delay)
                    continue

                raise GroqClientError(f"Network error: {e}") from e
            except GroqClientError as e:
                # Check if it's the tool_choice error
                if "tool choice is none" in str(e).lower() and "model called a tool" in str(e).lower():
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Groq tool_choice error on attempt {attempt + 1}/{max_retries}, retrying...")
                        await asyncio.sleep(0.5)
                        continue

                # Check if it's a rate limit error
                if e.status_code == 429 or "rate limit" in str(e).lower():
                    last_error = e
                    if attempt < max_retries - 1:
                        continue

                raise
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise GroqClientError(f"Unexpected error: {e}") from e

        # All retries exhausted
        if last_error:
            raise last_error
        raise GroqClientError("All retries exhausted")


# Global client instance (lazy initialization) with event loop tracking
_client: GroqClient | None = None
_client_event_loop: asyncio.AbstractEventLoop | None = None
_client_api_key: str | None = None


async def get_groq_client(
    api_key: str,
    model_version: str | None = None,
    default_model: GroqModel = GroqModel.OPENAI_GPT_OSS_120B,
    temperature: float = 0.6,
    max_tokens: int = 2048,
) -> GroqClient:
    """Get global Groq client instance (per event loop + api_key)"""
    global _client, _client_event_loop, _client_api_key

    current_loop = asyncio.get_event_loop()

    # Check if we need to recreate client due to event loop change or API key change
    if _client is not None and (_client_event_loop != current_loop or _client_api_key != api_key):
        _client = None
        _client_event_loop = None
        _client_api_key = None

    if _client is None:
        _client = GroqClient(
            api_key=api_key,
            model_version=model_version,
            default_model=default_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        _client_event_loop = current_loop
        _client_api_key = api_key
    return _client


async def cleanup_groq_client():
    """Cleanup global client"""
    global _client, _client_event_loop, _client_api_key
    if _client:
        try:
            await _client.close()
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                pass
            else:
                raise
        finally:
            _client = None
            _client_event_loop = None
            _client_api_key = None
