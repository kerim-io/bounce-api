"""
Groq API Models

Pydantic models for Groq reasoning API requests and responses.
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class GroqModel(str, Enum):
    """Supported Groq reasoning models"""

    DEEPSEEK_R1_DISTILL_LLAMA_70B = "deepseek-r1-distill-llama-70b"
    OPENAI_GPT_OSS_20B = "openai/gpt-oss-20b"
    OPENAI_GPT_OSS_120B = "openai/gpt-oss-120b"
    QWEN3_32B = "qwen/qwen3-32b"

    # Compound AI systems with built-in tools
    GROQ_COMPOUND = "groq/compound"
    GROQ_COMPOUND_MINI = "groq/compound-mini"


class ReasoningFormat(str, Enum):
    """Reasoning format options"""

    PARSED = "parsed"  # Separates reasoning into dedicated field
    RAW = "raw"  # Includes reasoning within <think> tags
    HIDDEN = "hidden"  # Returns only final answer


class ReasoningEffort(str, Enum):
    """Reasoning effort levels"""

    NONE = "none"  # Disable reasoning (Qwen 3 32B only)
    DEFAULT = "default"  # Enable reasoning (Qwen 3 32B only)
    LOW = "low"  # Low effort (GPT-OSS only)
    MEDIUM = "medium"  # Medium effort (GPT-OSS only)
    HIGH = "high"  # High effort (GPT-OSS only)


class ToolType(str, Enum):
    """Built-in tool types"""

    CODE_INTERPRETER = "code_interpreter"
    BROWSER_SEARCH = "browser_search"
    FUNCTION = "function"


class Message(BaseModel):
    """Chat message"""

    role: str = Field(..., description="Message role: system, user, assistant")
    content: str = Field(..., description="Message content")


class ToolFunction(BaseModel):
    """Function tool definition"""

    name: str = Field(..., description="Function name")
    description: str = Field(..., description="Function description")
    parameters: dict[str, Any] = Field(..., description="JSON schema for parameters")
    strict: bool = Field(default=True, description="Use strict mode")


class Tool(BaseModel):
    """Tool definition"""

    type: ToolType = Field(..., description="Tool type")
    function: ToolFunction | None = Field(default=None, description="Function definition")
    container: dict[str, str] | None = Field(default=None, description="Container config for code interpreter")


class ResponseFormat(BaseModel):
    """Response format for structured outputs"""

    type: str = Field(..., description="Response type: json_object, json_schema, text")
    json_schema: dict[str, Any] | None = Field(default=None, description="JSON schema for structured output")


class SearchSettings(BaseModel):
    """Search settings for Groq Compound web search"""

    exclude_domains: list[str] | None = Field(
        default=None,
        description="Domains to exclude from search (supports wildcards like *.com)",
    )
    include_domains: list[str] | None = Field(
        default=None,
        description="Restrict search to specific domains (supports wildcards like *.edu)",
    )
    country: str | None = Field(
        default=None,
        description="Boost search results from specific country code (e.g., 'us', 'uk')",
    )


class CompoundTools(BaseModel):
    """Tool configuration for Groq Compound systems"""

    enabled_tools: list[str] | None = Field(
        default=None,
        description=(
            "List of tool identifiers to enable: web_search, visit_website, "
            "code_interpreter, browser_automation, wolfram_alpha"
        ),
    )


class CompoundCustom(BaseModel):
    """Custom configuration for Groq Compound systems"""

    tools: CompoundTools | None = Field(default=None, description="Tool configuration")
    search_settings: SearchSettings | None = Field(default=None, description="Web search configuration")


class GroqChatRequest(BaseModel):
    """Groq chat completion request"""

    model: GroqModel = Field(..., description="Model to use")
    messages: list[Message] = Field(..., description="Conversation messages")

    # Core parameters
    temperature: float = Field(default=0.6, ge=0.0, le=2.0, description="Sampling temperature")
    max_completion_tokens: int = Field(default=1024, ge=1, description="Maximum completion tokens")
    top_p: float = Field(default=0.95, ge=0.0, le=1.0, description="Top-p sampling")
    stream: bool = Field(default=False, description="Enable streaming")
    stop: str | list[str] | None = Field(default=None, description="Stop sequences")
    seed: int | None = Field(default=None, description="Random seed for reproducibility")

    # Reasoning parameters
    reasoning_format: ReasoningFormat | None = Field(default=None, description="Reasoning format")
    reasoning_effort: ReasoningEffort | None = Field(default=None, description="Reasoning effort level")
    include_reasoning: bool | None = Field(default=None, description="Include reasoning (GPT-OSS only)")

    # Structured output
    response_format: ResponseFormat | None = Field(default=None, description="Structured response format")

    # Compound AI system parameters (groq/compound, groq/compound-mini)
    compound_custom: CompoundCustom | None = Field(
        default=None,
        description="Custom configuration for Groq Compound systems (tools, search settings)",
    )


class ChoiceDelta(BaseModel):
    """Streaming choice delta"""

    role: str | None = Field(default=None)
    content: str | None = Field(default=None)
    reasoning: str | None = Field(default=None)


class Choice(BaseModel):
    """Chat completion choice"""

    index: int = Field(..., description="Choice index")
    message: Message = Field(..., description="Response message")
    reasoning: str | None = Field(default=None, description="Model reasoning")
    finish_reason: str | None = Field(default=None, description="Finish reason")
    delta: ChoiceDelta | None = Field(default=None, description="Streaming delta")


class Usage(BaseModel):
    """Token usage statistics"""

    prompt_tokens: int = Field(..., description="Prompt tokens used")
    completion_tokens: int = Field(..., description="Completion tokens used")
    total_tokens: int = Field(..., description="Total tokens used")
    reasoning_tokens: int | None = Field(default=None, description="Reasoning tokens used")


class ExecutedTool(BaseModel):
    """Tool execution details from Compound systems"""

    type: str = Field(..., description="Tool type (web_search, code_interpreter, etc.)")
    input: dict[str, Any] | None = Field(default=None, description="Tool input parameters")
    output: Any | None = Field(default=None, description="Tool output")


class GroqChatResponse(BaseModel):
    """Groq chat completion response"""

    id: str = Field(..., description="Response ID")
    object: str = Field(..., description="Object type")
    created: int = Field(..., description="Creation timestamp")
    model: str = Field(..., description="Model used")
    choices: list[Choice] = Field(..., description="Response choices")
    usage: Usage | None = Field(default=None, description="Token usage")
    executed_tools: list[ExecutedTool] | None = Field(
        default=None,
        description="Tools executed by Compound systems (web_search, code_interpreter, etc.)",
    )


class GroqReasoningRequest(BaseModel):
    """High-level reasoning request"""

    user_id: str = Field(..., description="User ID for access control")
    prompt: str = Field(..., description="Reasoning prompt")
    model: GroqModel = Field(default=GroqModel.DEEPSEEK_R1_DISTILL_LLAMA_70B, description="Model to use")
    reasoning_format: ReasoningFormat = Field(default=ReasoningFormat.PARSED, description="Reasoning format")
    reasoning_effort: ReasoningEffort | None = Field(default=None, description="Reasoning effort")
    temperature: float = Field(default=0.6, ge=0.0, le=2.0, description="Temperature")
    max_tokens: int = Field(default=1024, ge=1, description="Max tokens")
    enable_tools: bool = Field(default=False, description="Enable built-in tools")


class GroqReasoningResponse(BaseModel):
    """High-level reasoning response"""

    request_id: str = Field(..., description="Request ID")
    user_id: str = Field(..., description="User ID")
    model: str = Field(..., description="Model used")
    response: str = Field(..., description="Final response")
    reasoning: str | None = Field(default=None, description="Reasoning content")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Creation time")
    usage: Usage | None = Field(default=None, description="Token usage")


class GroqEmbeddingRequest(BaseModel):
    """Groq embedding request"""

    model: str = Field(default="text-embedding-3-small", description="Embedding model to use")
    input: str | list[str] = Field(..., description="Text(s) to embed")
    encoding_format: str = Field(default="float", description="Encoding format")
    dimensions: int | None = Field(default=None, description="Number of dimensions (model specific)")


class EmbeddingData(BaseModel):
    """Single embedding data"""

    object: str = Field(..., description="Object type")
    embedding: list[float] = Field(..., description="Embedding vector")
    index: int = Field(..., description="Input index")


class GroqEmbeddingResponse(BaseModel):
    """Groq embedding response"""

    object: str = Field(..., description="Object type")
    data: list[EmbeddingData] = Field(..., description="Embedding data")
    model: str = Field(..., description="Model used")
    usage: Usage | None = Field(default=None, description="Token usage")


class GroqErrorResponse(BaseModel):
    """Groq error response"""

    error: str = Field(..., description="Error message")
    type: str = Field(..., description="Error type")
    code: str | None = Field(default=None, description="Error code")
    param: str | None = Field(default=None, description="Invalid parameter")
