"""
LLM Factory - Simplified provider abstraction for GenerativeMixin

Provides unified request/response models with Groq as the primary provider.
"""

from pydantic import BaseModel, Field

from .providers.groq import GroqClient
from .providers.groq import Message as GroqMessage


class Message(BaseModel):
    """Unified message model for all LLM providers"""

    role: str = Field(..., description="Message role: system, user, assistant")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Unified chat request model for all LLM providers"""

    messages: list[Message] = Field(..., description="Conversation messages")
    temperature: float = Field(default=0.6, ge=0.0, le=2.0, description="Sampling temperature")
    max_completion_tokens: int = Field(default=1024, ge=1, description="Maximum completion tokens")
    model: str | None = Field(default=None, description="Model name (provider-specific)")


class Choice(BaseModel):
    """Unified choice model"""

    index: int
    message: Message
    finish_reason: str | None = None


class Usage(BaseModel):
    """Unified usage statistics"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatResponse(BaseModel):
    """Unified chat response model for all LLM providers"""

    id: str
    choices: list[Choice]
    usage: Usage | None = None


async def chat_completion(client: GroqClient, request: ChatRequest) -> ChatResponse:
    """
    Execute chat completion using Groq client.

    Args:
        client: Groq client instance
        request: Unified ChatRequest

    Returns:
        Unified ChatResponse
    """
    from .providers.groq import GroqChatRequest, GroqModel

    # Get model from request or client default
    model_str = request.model or client.default_model.value
    if "compound-mini" in model_str.lower():
        model = GroqModel.GROQ_COMPOUND_MINI
    elif "compound" in model_str.lower():
        model = GroqModel.GROQ_COMPOUND
    elif "gpt-oss-120b" in model_str.lower():
        model = GroqModel.OPENAI_GPT_OSS_120B
    elif "gpt-oss-20b" in model_str.lower():
        model = GroqModel.OPENAI_GPT_OSS_20B
    elif "deepseek" in model_str.lower():
        model = GroqModel.DEEPSEEK_R1_DISTILL_LLAMA_70B
    else:
        model = client.default_model

    # Convert unified request to Groq format
    groq_request = GroqChatRequest(
        model=model,
        messages=[GroqMessage(role=msg.role, content=msg.content) for msg in request.messages],
        temperature=request.temperature,
        max_completion_tokens=request.max_completion_tokens,
    )

    response = await client.chat_completion(groq_request)

    # Convert to unified response
    return ChatResponse(
        id=response.id,
        choices=[
            Choice(
                index=choice.index,
                message=Message(role=choice.message.role, content=choice.message.content),
                finish_reason=choice.finish_reason,
            )
            for choice in response.choices
        ],
        usage=Usage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        )
        if response.usage
        else None,
    )
