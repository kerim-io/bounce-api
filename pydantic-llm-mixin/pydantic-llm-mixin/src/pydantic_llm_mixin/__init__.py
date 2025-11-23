"""
Pydantic LLM Mixin - Turn any Pydantic model into an LLM-generated instance

==============================================================================
WHAT THIS PACKAGE DOES
==============================================================================

This package provides GenerativeMixin - a mixin class that adds LLM generation
capabilities to any Pydantic model. Instead of manually creating instances,
you can generate them from natural language using Groq's reasoning models.

Key Features:
- Multi-strategy JSON extraction from LLM responses (4 fallback strategies)
- Robust retry logic with exponential backoff for transient errors
- Clean provider abstraction (Groq primary, extensible to Claude/OpenAI)
- Type-safe Pydantic validation - trust the schema
- Built-in rate limiting (300 req/min, 144k req/day)
- Streaming callbacks for real-time updates
- Custom validation support beyond Pydantic schema

==============================================================================
INSTALLATION
==============================================================================

From PyPI (public release):
    pip install pydantic-llm-mixin

From private GitHub repo (for Mari-OS projects):
    export GITHUB_TOKEN="ghp_your_token_here"
    uv pip install "git+https://$GITHUB_TOKEN@github.com/aceeyz/pydantic-llm-mixin.git"

Add to pyproject.toml:
    [project]
    dependencies = ["pydantic-llm-mixin"]

    [tool.uv.sources]
    pydantic-llm-mixin = { git = "https://github.com/aceeyz/pydantic-llm-mixin.git", branch = "main" }

Railway deployment: GITHUB_TOKEN auto-injected, zero config needed.

==============================================================================
BASIC USAGE
==============================================================================

Step 1: Define a Pydantic model with GenerativeMixin

    from pydantic import BaseModel, Field
    from pydantic_llm_mixin import GenerativeMixin, get_groq_client

    class Person(BaseModel, GenerativeMixin):
        name: str = Field(..., description="Person's full name")
        age: int = Field(..., description="Person's age in years")
        occupation: str = Field(..., description="Current job title")

Step 2: Initialize Groq client (get API key from https://console.groq.com/home)

    client = await get_groq_client(api_key="your-groq-api-key")

Step 3: Generate instance from conversation

    conversation = [
        {"role": "user", "content": "Tell me about Nikola Tesla"}
    ]

    person = await Person.generate_instance(
        client=client,
        conversation_history=conversation
    )

    print(f"{person.name}, {person.age}, {person.occupation}")
    # Output: Nikola Tesla, 86, Electrical Engineer and Inventor

==============================================================================
ADVANCED FEATURES
==============================================================================

Custom Validation (beyond Pydantic schema):
    def validate_cast_size(instance: MovieCast) -> tuple[bool, str | None]:
        if len(instance.actors) != 3:
            return False, f"Need exactly 3 actors, got {len(instance.actors)}"
        return True, None

    cast = await MovieCast.generate_instance(
        client=client,
        conversation_history=conversation,
        validation_callback=validate_cast_size  # Retry until valid
    )

Streaming Callbacks (real-time events):
    async def stream_callback(event_data: tuple[str, dict]):
        event_type, data = event_data
        if event_type == "raw_llm_response":
            print(f"LLM: {data['response'][:100]}...")
        elif event_type == "parsed_instance":
            print(f"Parsed: {data['instance']}")

    person = await Person.generate_instance(
        client=client,
        conversation_history=conversation,
        streaming_callback=stream_callback
    )

System-Managed Fields (excluded from LLM schema):
    from uuid import UUID, uuid4
    from datetime import datetime, timezone

    class Task(BaseModel, GenerativeMixin):
        # System-managed - auto-generated, LLM won't see these
        id: UUID = Field(default_factory=uuid4, json_schema_extra={"system_managed": True})
        created_at: datetime = Field(
            default_factory=lambda: datetime.now(timezone.utc), json_schema_extra={"system_managed": True}
        )

        # User-facing - LLM generates these
        title: str = Field(..., description="Task title")
        priority: str = Field(..., description="Priority: low, medium, high")

Conversation History (automatic trimming to last 3-5 exchanges):
    conversation = [
        {"role": "user", "content": "Who invented the telephone?"},
        {"role": "assistant", "content": "Alexander Graham Bell"},
        {"role": "user", "content": "What about Tesla?"},
        {"role": "assistant", "content": "Nikola Tesla invented AC electrical systems"},
        {"role": "user", "content": "Tell me more about Tesla"}  # Current query
    ]
    # Mixin automatically keeps last 3-5 complete user+assistant exchanges

==============================================================================
ERROR HANDLING
==============================================================================

    from pydantic_llm_mixin import GenerationError

    try:
        person = await Person.generate_instance(
            client=client,
            conversation_history=conversation,
            max_retries=3
        )
    except GenerationError as e:
        print(f"Generation failed after all retries: {e}")
        # Full traceback logged automatically

Retry behavior:
- Transient LLM errors (rate limits, 503, tool_choice): Exponential backoff
- JSON parsing errors: Retry with base delay
- Validation errors: Retry with base delay
- Non-transient errors: Fail immediately with full traceback

==============================================================================
SUPPORTED MODELS (Groq)
==============================================================================

    from pydantic_llm_mixin import GroqModel

    GroqModel.OPENAI_GPT_OSS_120B  # Default - best for complex reasoning
    GroqModel.OPENAI_GPT_OSS_20B   # Faster, smaller model
    GroqModel.DEEPSEEK_R1_DISTILL_LLAMA_70B  # DeepSeek reasoning
    GroqModel.QWEN3_32B  # Qwen reasoning model
    GroqModel.GROQ_COMPOUND  # Compound AI with built-in tools
    GroqModel.GROQ_COMPOUND_MINI  # Smaller compound system

==============================================================================
RATE LIMITING
==============================================================================

Built-in token bucket algorithm:
- 300 requests/minute (Groq Dev tier)
- 144,000 requests/day
- Exponential backoff on rate limit errors
- Automatic retry on 429 responses

No manual rate limiting needed - handled transparently.

==============================================================================
ARCHITECTURE
==============================================================================

Core Components:
1. GenerativeMixin - Mixin providing generate_instance() method
2. GroqClient - Async client with rate limiting and retry logic
3. Factory - Provider abstraction layer (unified request/response models)
4. JSON Extraction - Multi-strategy extraction (regex, manual, brace-matching, raw)

Multi-Strategy JSON Extraction:
1. Regex pattern - ```json\n{...}\n```
2. Manual block parsing - Handle nested backticks
3. Brace matching - Find complete {...} blocks
4. Raw JSON - Try parsing entire response

Handles LLM quirks without sacrificing correctness.

==============================================================================
DEPLOYMENT
==============================================================================

Railway Deployment:
1. Visit https://railway.com?referralCode=d3k_vU (get credits)
2. Create project from GitHub repo
3. Set GROQ_API_KEY environment variable
4. Railway auto-deploys (GITHUB_TOKEN injected automatically)

See examples/railway_deployment.py for FastAPI server example.

==============================================================================
PHILOSOPHY - TRUST THE LLM
==============================================================================

Minimal prompting:
- Field descriptions ARE the spec
- LLM infers everything from Pydantic schema
- Don't over-prompt, let the LLM decide
- Schema-first design

Fail-fast architecture:
- Full tracebacks on errors
- No silent failures
- One execution path only
- Validate at startup

Type-safe:
- 100% Pydantic validation
- No dict conversions, no Any types
- Runtime type validation

==============================================================================
CREDITS
==============================================================================

Built by Alan Eyzaguirre at Eyzaguirre.co

Combines best-of-breed patterns from:
- mari-pydantic-orm: Authentication context and robust error handling
- mari-agentic-llm: Clean provider abstraction
- fast_spacy: Multi-strategy JSON extraction

GitHub: https://github.com/aceeyz/pydantic-llm-mixin
License: MIT
"""

from .errors import GenerationError
from .factory import ChatRequest, ChatResponse, Message
from .generative_mixin import GenerativeMixin
from .providers.groq import (
    GroqClient,
    GroqClientError,
    GroqModel,
    get_groq_client,
)

__version__ = "0.1.0"

__all__ = [
    # Core mixin
    "GenerativeMixin",
    # Errors
    "GenerationError",
    # Factory models
    "ChatRequest",
    "ChatResponse",
    "Message",
    # Groq provider
    "GroqClient",
    "GroqClientError",
    "GroqModel",
    "get_groq_client",
]
