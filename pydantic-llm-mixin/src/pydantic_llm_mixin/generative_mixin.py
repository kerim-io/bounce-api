"""
Generative Mixin for Pydantic Models

Best-of-breed implementation combining patterns from:
- mari-pydantic-orm: Authentication context and robust error handling
- mari-agentic-llm: Clean provider abstraction
- fast_spacy: Multi-strategy JSON extraction

This mixin adds LLM generation capabilities to any Pydantic model using the Groq client.
Trust Pydantic validation and LLM JSON generation with robust fallback strategies.
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC
from typing import Any, Self

from pydantic import ValidationError
from rich.console import Console

from .errors import GenerationError
from .factory import ChatRequest, Message, chat_completion
from .prompts import CONVERSATION_HISTORY_LIMITS, SCHEMA_SYSTEM_MESSAGE_TEMPLATE

logger = logging.getLogger(__name__)
console = Console()

# JSON extraction pattern for LLM responses (DOTALL | MULTILINE as requested)
JSON_PATTERN = re.compile(r"```json\s*([^`]+)\s*```", re.DOTALL | re.MULTILINE)


class GenerativeMixin:
    """
    Mixin providing generative AI capabilities to Pydantic models.

    This mixin enables any Pydantic model to generate instances from natural language
    using Groq's reasoning models with robust error handling and retry logic.
    """

    @classmethod
    def model_json_schema(cls, **kwargs):
        """
        Override Pydantic's model_json_schema to filter system-managed fields.

        System-managed fields (like id, created_at from BasePersistableModel) are marked
        with json_schema_extra={"system_managed": True}. These fields should not appear
        in LLM tool schemas since the LLM shouldn't generate them.

        This keeps LLM tool schemas clean while allowing proper Pydantic serialization
        for database persistence.
        """
        # Get the standard schema from Pydantic
        schema = super().model_json_schema(**kwargs)

        # Filter out system-managed fields from properties
        if "properties" in schema:
            schema["properties"] = {
                field_name: field_schema
                for field_name, field_schema in schema["properties"].items()
                if not (
                    field_schema.get("json_schema_extra", {}).get("system_managed", False)
                    or field_schema.get("system_managed", False)  # Pydantic unpacks json_schema_extra
                )
            }

            # Also remove from required list if present
            if "required" in schema:
                filtered_properties = set(schema["properties"].keys())
                schema["required"] = [field for field in schema["required"] if field in filtered_properties]

        return schema

    def get_display_content(self) -> str:
        """
        Get display string - caller decides what to do with it.

        Default implementation returns JSON dump excluding system-managed fields.
        Override in subclasses for custom formatting.

        Returns:
            Formatted string for display

        Examples:
            - ReasoningDecision: "Continue: Using calculator for arithmetic"
            - Expert: "SQL: SELECT ... | Reasoning: ... | Next: analyze_results"
            - MariEngine: "Selected Journey: MovieDirector | Reasoning: ..."
        """
        from pydantic import BaseModel

        if isinstance(self, BaseModel):
            # Exclude system-managed fields
            exclude_fields = {"id", "created_at", "updated_at", "user_id", "raw_llm_response"}
            data = self.model_dump(exclude=exclude_fields)
            return json.dumps(data, indent=2, default=str)
        return str(self)

    @classmethod
    async def generate_instance(
        cls,
        client: Any,  # GroqClient instance
        conversation_history: list[dict[str, str]],
        temperature: float = 0.6,
        max_tokens: int = 2048,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        debug: bool = False,
        streaming_callback: Callable | None = None,
        validation_callback: Callable[[Self], tuple[bool, str | None]] | None = None,
    ) -> Self:
        """
        Generate an instance of this Pydantic model using an LLM.

        Trust Pydantic validation and LLM JSON generation with multiple retry strategies.

        Args:
            client: GroqClient instance (required)
            conversation_history: List of messages with 'role' and 'content'. Must include at least one user message.
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum completion tokens
            max_retries: Maximum retry attempts on failure
            retry_base_delay: Base delay for retry backoff (seconds)
            debug: Enable debug logging
            streaming_callback: Optional async callback for streaming tokens as they arrive
            validation_callback: Optional callback to validate instance after Pydantic validation.
                               Returns (is_valid, feedback_message). If invalid, feedback is added
                               to retry context. Useful for complex constraints like "must have exactly 30 items".

        Returns:
            Generated and validated Pydantic model instance

        Raises:
            GenerationError: If generation fails after all retries
            TypeError: If streaming_callback is not None and not callable
        """
        # FAIL FAST: Validate streaming_callback is callable if provided
        if streaming_callback is not None and not callable(streaming_callback):
            raise TypeError(
                f"streaming_callback must be callable if provided, got {type(streaming_callback).__name__}"
            )

        last_exception = None

        # Retry loop with exponential backoff
        for attempt in range(max_retries):
            try:
                # Generate schema-only system prompt
                schema_prompt = cls._generate_prompt(max_tokens=max_tokens)

                # Build messages: schema system message + conversation history
                messages = []
                messages.append(Message(role="system", content=schema_prompt))

                # Select last 3-5 complete exchanges from conversation history
                selected_history = cls._select_recent_exchanges(
                    conversation_history, max_exchanges=CONVERSATION_HISTORY_LIMITS["max_exchanges"]
                )

                # Add selected conversation history - create fresh Message objects
                for msg in selected_history:
                    # Duck typing: if it has .role and .content, it's a Message object
                    if hasattr(msg, "role") and hasattr(msg, "content"):
                        assert isinstance(msg.role, str), f"role must be str, got {type(msg.role)}"
                        assert isinstance(msg.content, str), f"content must be str, got {type(msg.content)}"
                        messages.append(Message(role=msg.role, content=msg.content))
                    else:
                        messages.append(Message(role=msg["role"], content=msg["content"]))

                # Create chat request
                request = ChatRequest(
                    messages=messages,
                    temperature=temperature,
                    max_completion_tokens=max_tokens,
                )

                # Get LLM response
                response = await chat_completion(client, request)

                if not response.choices:
                    raise GenerationError("No response choices returned from LLM")

                full_response = response.choices[0].message.content or ""

                if not full_response:
                    raise GenerationError("No response content received from LLM")

                # Stream raw LLM response if callback provided
                if streaming_callback:
                    await streaming_callback(("raw_llm_response", {"model": cls.__name__, "response": full_response}))

                # Extract JSON using multi-strategy approach
                try:
                    json_str = cls._extract_json(full_response)
                except Exception as e:
                    logger.error("JSON extraction failed:")
                    logger.error(f"  Error: {e}")
                    logger.error(f"  Full LLM response (first 500 chars): {full_response[:500]}")
                    logger.error(f"  Full LLM response (last 500 chars): {full_response[-500:]}")
                    raise

                # Parse and validate JSON
                try:
                    instance_data = json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.error("JSON parse failed:")
                    logger.error(f"  Error: {e}")
                    logger.error(f"  Extracted JSON (first 500 chars): {json_str[:500]}")
                    logger.error(f"  Extracted JSON (last 500 chars): {json_str[-500:]}")
                    logger.error(f"  Full LLM response (first 300 chars): {full_response[:300]}")
                    raise

                # Trust Pydantic validation - let it handle the schema
                try:
                    instance = cls.model_validate(instance_data)
                except ValidationError as e:
                    logger.error("Pydantic validation failed:")
                    logger.error(f"  Error: {e}")
                    logger.error(f"  Instance data keys: {list(instance_data.keys())}")
                    raise

                # Store the raw LLM response if the instance has the field
                if hasattr(instance, "raw_llm_response"):
                    instance.raw_llm_response = full_response

                # Stream parsed instance if callback provided
                if streaming_callback:
                    await streaming_callback(
                        ("parsed_instance", {"model": cls.__name__, "instance": instance.model_dump()})
                    )

                # Run custom validation callback if provided
                if validation_callback:
                    is_valid, feedback = validation_callback(instance)
                    if not is_valid:
                        error_msg = feedback or "Custom validation failed"
                        if debug:
                            logger.warning(f"❌ Validation callback failed: {error_msg}")
                        raise ValueError(f"Validation failed: {error_msg}")

                return instance

            except Exception as e:
                # Check if this is an LLM client error (e.g., API errors)
                error_msg = str(e).lower()
                is_llm_error = (
                    "client" in type(e).__name__.lower()
                    or "api" in error_msg
                    or "internal server error" in error_msg
                    or "tool choice" in error_msg
                    or "model called a tool" in error_msg
                    or "503" in error_msg
                    or "502" in error_msg
                    or "rate limit" in error_msg
                )

                # Retry on transient LLM errors
                if is_llm_error and attempt < max_retries - 1:
                    logger.warning(f"Transient LLM error on attempt {attempt + 1}/{max_retries}, retrying: {e}")
                    await asyncio.sleep(retry_base_delay * (attempt + 1))
                    continue

                # If it's a JSON parsing error, don't retry here - let the next except block handle it
                if isinstance(e, json.JSONDecodeError):
                    raise

                # Non-transient error or max retries exhausted
                logger.error(f"LLM client failed after all retries: {e}")
                raise GenerationError(f"LLM API error after retries: {e}") from e

            except (
                ValidationError,
                json.JSONDecodeError,
                ValueError,
            ) as e:
                # ONLY retry on parsing/validation errors (LLM returned bad JSON)
                last_exception = e

                if debug:
                    logger.warning(f"❌ Generation attempt {attempt + 1} failed: {e}")

                # Short retry on parsing errors
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_base_delay)

        # All retries exhausted
        error_msg = f"Failed to generate {cls.__name__} after {max_retries} attempts"
        if last_exception:
            error_msg += f". Last error: {last_exception}"

        logger.error(error_msg)
        raise GenerationError(error_msg) from last_exception

    @classmethod
    def _generate_prompt(cls, max_tokens: int | None = None, prompt_style: str | None = None) -> str:
        """Generate pure schema system prompt with optional style-based formatting guidance."""
        from datetime import datetime

        if max_tokens is None:
            max_tokens = 2048

        schema = cls.model_json_schema()
        schema_json = json.dumps(schema, indent=2)

        # Get current date
        current_date = datetime.now(UTC).strftime("%Y-%m-%d")

        # Placeholder for formatting guidance (can be extended)
        formatting_guidance = ""

        return SCHEMA_SYSTEM_MESSAGE_TEMPLATE.format(
            current_date=current_date, schema_json=schema_json, formatting_guidance=formatting_guidance
        )

    @classmethod
    def _select_recent_exchanges(cls, history: list, max_exchanges: int = 5) -> list:
        """
        Select last 3-5 complete user+assistant exchanges from conversation history.

        An "exchange" is a user message followed by an assistant response.
        This prevents cutting off exchanges mid-conversation.

        Args:
            history: Full conversation history (list of dicts or Message objects)
            max_exchanges: Maximum number of exchanges to keep (default: 5)

        Returns:
            Trimmed history with last N complete exchanges
        """
        min_exchanges = CONVERSATION_HISTORY_LIMITS["min_exchanges"]
        max_messages = max_exchanges * 2  # Each exchange = user + assistant

        # If history is short enough, return it all
        if len(history) <= min_exchanges * 2:
            return history

        # Keep last N exchanges (N*2 messages)
        return history[-max_messages:]

    @classmethod
    def _extract_json(cls, text: str) -> str:
        """
        Extract JSON from LLM response with multiple fallback strategies.

        Uses the robust multi-strategy approach from fast_spacy implementation.
        """
        # Strategy 1: Standard regex pattern (DOTALL | MULTILINE)
        match = JSON_PATTERN.search(text)
        if match:
            json_content = match.group(1).strip()
            try:
                # Validate it's actually valid JSON
                json.loads(json_content)
                return json_content
            except json.JSONDecodeError:
                pass  # Fall through to next strategy

        # Strategy 2: Manual json block parsing with nested backtick handling
        json_start = text.find("```json")
        if json_start >= 0:
            # Find content after ```json
            content_start = json_start + 7  # len('```json')

            # Look for closing ``` but account for potential nested content
            lines = text[content_start:].split("\n")
            json_lines = []

            for line in lines:
                if line.strip() == "```" and json_lines:
                    # Found closing, try to parse what we have
                    break
                json_lines.append(line)

            if json_lines:
                potential_json = "\n".join(json_lines).strip()
                try:
                    # Validate it's actually JSON
                    json.loads(potential_json)
                    return potential_json
                except json.JSONDecodeError:
                    pass  # Fall through to next strategy

        # Strategy 3: Look for { ... } blocks with brace matching
        brace_start = text.find("{")
        if brace_start >= 0:
            brace_count = 0
            for i, char in enumerate(text[brace_start:], brace_start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        potential_json = text[brace_start : i + 1]
                        try:
                            json.loads(potential_json)
                            return potential_json
                        except json.JSONDecodeError:
                            continue  # Keep looking for next complete brace block

        # Strategy 4: Look for JSON-like content without markdown
        try:
            # Try parsing the entire text as JSON
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass

        # All strategies failed - provide detailed error information
        json_start = text.find("```json")
        json_end = text.rfind("```")

        if json_start >= 0:
            context_start = max(0, json_start - 50)
            context_end = min(len(text), (json_end + 50) if json_end > json_start else len(text))
            context = text[context_start:context_end]
            raise ValueError(f"JSON block found but extraction failed with all strategies. Context: ...{context}...")
        else:
            # Truncate text for error message
            preview = text[:500] + ("..." if len(text) > 500 else "")
            raise ValueError(f"No JSON block found in LLM response. Response preview: {preview}")

    async def generate_text(
        self,
        client: Any,  # GroqClient instance
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.6,
        debug: bool = False,
    ) -> str:
        """
        Generate text using Groq client directly (for non-structured generation).

        Args:
            client: GroqClient instance
            prompt: Text generation prompt
            max_tokens: Maximum completion tokens
            temperature: Sampling temperature
            debug: Enable debug logging

        Returns:
            Generated text content
        """
        try:
            # Use factory for provider-agnostic completion
            request = ChatRequest(
                messages=[Message(role="user", content=prompt)],
                temperature=temperature,
                max_completion_tokens=max_tokens,
            )

            response = await chat_completion(client, request)

            if response.choices:
                content = response.choices[0].message.content or ""
                return content.strip()
            else:
                return "No response generated"

        except Exception as e:
            logger.error(f"Text generation failed: {e}")
            return f"Error generating text: {e}"

    async def generate_summary(
        self, client: Any, max_length: int = 200, debug: bool = False  # GroqClient instance
    ) -> str:
        """Generate concise summary of this model instance."""
        from pydantic import BaseModel

        if isinstance(self, BaseModel):
            model_data = self.model_dump(exclude={"id", "created_at", "updated_at"})
        else:
            model_data = vars(self)

        prompt = f"""Create a concise summary (max {max_length} characters) of this {self.__class__.__name__}:

{json.dumps(model_data, indent=2)}

Focus on the most important aspects and keep it under {max_length} characters."""

        summary = await self.generate_text(
            client,
            prompt,
            max_tokens=max_length // 2,
            debug=debug,
        )

        # Truncate if necessary
        if len(summary) > max_length:
            summary = summary[: max_length - 3] + "..."

        return summary
