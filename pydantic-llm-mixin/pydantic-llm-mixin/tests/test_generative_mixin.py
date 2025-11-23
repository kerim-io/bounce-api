"""
Tests for GenerativeMixin

Demonstrates usage patterns and validates core functionality.
"""

import os

import pytest
from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerativeMixin, get_groq_client


class Person(BaseModel, GenerativeMixin):
    """Test model for person data"""

    name: str = Field(..., description="Person's full name")
    age: int = Field(..., description="Person's age in years")
    occupation: str = Field(..., description="Current job title")


@pytest.fixture
async def groq_client():
    """Get Groq client for tests"""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        pytest.skip("GROQ_API_KEY not set")

    assert api_key is not None, "GROQ_API_KEY must be set"
    client = await get_groq_client(api_key=api_key, temperature=0.6, max_tokens=2048)
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_basic_generation(groq_client):
    """Test basic instance generation"""
    conversation = [{"role": "user", "content": "Tell me about Nikola Tesla"}]

    person = await Person.generate_instance(client=groq_client, conversation_history=conversation)

    assert person.name
    assert person.age > 0
    assert person.occupation
    assert "tesla" in person.name.lower()


@pytest.mark.asyncio
async def test_conversation_history(groq_client):
    """Test with conversation history"""
    conversation = [
        {"role": "user", "content": "Who invented the telephone?"},
        {"role": "assistant", "content": "Alexander Graham Bell"},
        {"role": "user", "content": "What about Tesla?"},
        {"role": "assistant", "content": "Nikola Tesla invented AC electrical systems"},
        {"role": "user", "content": "Tell me more about Tesla"},
    ]

    person = await Person.generate_instance(client=groq_client, conversation_history=conversation)

    assert "tesla" in person.name.lower()


@pytest.mark.asyncio
async def test_custom_validation(groq_client):
    """Test custom validation callback"""

    class MovieCast(BaseModel, GenerativeMixin):
        actors: list[str] = Field(..., description="List of main actors")
        director: str = Field(..., description="Film director")

    def validate_cast_size(instance: MovieCast) -> tuple[bool, str | None]:
        if len(instance.actors) != 3:
            return False, f"Need exactly 3 actors, got {len(instance.actors)}"
        return True, None

    conversation = [{"role": "user", "content": "Give me the cast of The Matrix with exactly 3 main actors"}]

    cast = await MovieCast.generate_instance(
        client=groq_client, conversation_history=conversation, validation_callback=validate_cast_size, max_retries=5
    )

    assert len(cast.actors) == 3
    assert cast.director


@pytest.mark.asyncio
async def test_streaming_callback(groq_client):
    """Test streaming callback"""
    events = []

    async def stream_callback(event_data: tuple[str, dict]):
        events.append(event_data)

    conversation = [{"role": "user", "content": "Tell me about Albert Einstein"}]

    person = await Person.generate_instance(
        client=groq_client, conversation_history=conversation, streaming_callback=stream_callback
    )

    # Should have received raw_llm_response and parsed_instance events
    event_types = [event[0] for event in events]
    assert "raw_llm_response" in event_types
    assert "parsed_instance" in event_types

    assert "einstein" in person.name.lower()


@pytest.mark.asyncio
async def test_json_extraction():
    """Test JSON extraction strategies"""
    from pydantic_llm_mixin.generative_mixin import GenerativeMixin

    # Strategy 1: Markdown code block
    text1 = """Here's the data:
```json
{"name": "Test", "age": 30, "occupation": "Engineer"}
```
"""
    json_str = GenerativeMixin._extract_json(text1)
    assert "Test" in json_str

    # Strategy 2: Raw JSON with braces
    text2 = '{"name": "Test", "age": 30, "occupation": "Engineer"}'
    json_str = GenerativeMixin._extract_json(text2)
    assert "Test" in json_str

    # Strategy 3: JSON with surrounding text
    text3 = 'Here is the result: {"name": "Test", "age": 30, "occupation": "Engineer"} Hope this helps!'
    json_str = GenerativeMixin._extract_json(text3)
    assert "Test" in json_str


@pytest.mark.asyncio
async def test_system_managed_fields():
    """Test that system-managed fields are excluded from schema"""
    from uuid import UUID, uuid4

    class Task(BaseModel, GenerativeMixin):
        id: UUID = Field(default_factory=uuid4, json_schema_extra={"system_managed": True})
        title: str = Field(..., description="Task title")
        description: str = Field(..., description="Task description")

    schema = Task.model_json_schema()

    # System-managed field should be excluded
    assert "id" not in schema["properties"]

    # User fields should be present
    assert "title" in schema["properties"]
    assert "description" in schema["properties"]


@pytest.mark.asyncio
async def test_error_handling(groq_client):
    """Test error handling with invalid input"""

    # Empty conversation should raise error
    with pytest.raises(Exception):
        await Person.generate_instance(client=groq_client, conversation_history=[], max_retries=1)
