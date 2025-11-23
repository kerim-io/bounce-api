# Quick Start Guide

Get up and running with Pydantic LLM Mixin in 5 minutes.

## Installation

```bash
pip install pydantic-llm-mixin
```

## Get Your Groq API Key

Groq provides blazing-fast inference for LLM generation with a generous free tier:

1. Visit [Groq Console](https://console.groq.com/home)
2. Sign up for a free account
3. Navigate to API Keys section
4. Generate a new API key
5. Set environment variable:

```bash
export GROQ_API_KEY="gsk_..."
```

**Free tier includes:**
- 30 requests/minute
- 14,400 requests/day
- Access to reasoning models (DeepSeek R1, GPT-OSS 120B, Qwen3 32B)

## Optional: Deploy on Railway

For production deployments:

1. Visit [Railway](https://railway.com?referralCode=d3k_vU) - use referral code for credits
2. Create a new project from your GitHub repo
3. Add `GROQ_API_KEY` to environment variables
4. Deploy with zero configuration

Railway provides:
- Automatic HTTPS
- Environment variable management
- Built-in metrics and logging
- Pay-as-you-go pricing

## Your First Generation

Create `example.py`:

```python
import asyncio
import os
from pydantic import BaseModel, Field
from pydantic_llm_mixin import GenerativeMixin, get_groq_client

class Person(BaseModel, GenerativeMixin):
    name: str = Field(..., description="Full name")
    age: int = Field(..., description="Age in years")
    occupation: str = Field(..., description="Job title")

async def main():
    # Get client
    client = await get_groq_client(api_key=os.getenv("GROQ_API_KEY"))

    # Generate instance
    person = await Person.generate_instance(
        client=client,
        conversation_history=[
            {"role": "user", "content": "Tell me about Ada Lovelace"}
        ]
    )

    print(f"{person.name}, {person.age}, {person.occupation}")
    await client.close()

asyncio.run(main())
```

Run it:
```bash
python example.py
```

Output:
```
Ada Lovelace, 36, Mathematician and Writer
```

## Common Patterns

### Multi-turn Conversation

```python
conversation = [
    {"role": "user", "content": "Who invented the computer?"},
    {"role": "assistant", "content": "Charles Babbage designed the Analytical Engine"},
    {"role": "user", "content": "Who programmed it?"}
]

person = await Person.generate_instance(
    client=client,
    conversation_history=conversation
)
# Gets Ada Lovelace
```

### Custom Validation

```python
def validate_age(instance: Person) -> tuple[bool, str | None]:
    if instance.age < 0 or instance.age > 150:
        return False, "Age must be 0-150"
    return True, None

person = await Person.generate_instance(
    client=client,
    conversation_history=[...],
    validation_callback=validate_age
)
```

### Complex Models

```python
class MovieCast(BaseModel, GenerativeMixin):
    title: str = Field(..., description="Movie title")
    director: str = Field(..., description="Director name")
    actors: list[str] = Field(..., description="Main actors")
    year: int = Field(..., description="Release year")
    genre: str = Field(..., description="Primary genre")

cast = await MovieCast.generate_instance(
    client=client,
    conversation_history=[
        {"role": "user", "content": "Tell me about The Matrix"}
    ]
)
```

### Debug Mode

```python
person = await Person.generate_instance(
    client=client,
    conversation_history=[...],
    debug=True  # Enables detailed logging
)
```

## Configuration

### Temperature

Higher = more creative, Lower = more deterministic

```python
client = await get_groq_client(
    api_key=api_key,
    temperature=0.8  # More creative (default: 0.6)
)
```

### Max Tokens

```python
client = await get_groq_client(
    api_key=api_key,
    max_tokens=4096  # Longer responses (default: 2048)
)
```

### Retries

```python
person = await Person.generate_instance(
    client=client,
    conversation_history=[...],
    max_retries=5  # More retry attempts (default: 3)
)
```

## Troubleshooting

### Rate Limits

The client handles rate limits automatically with exponential backoff. If you see rate limit warnings, the client is working correctly - just wait.

### JSON Extraction Failures

If you get JSON extraction errors:
1. Check that your field descriptions are clear
2. Try increasing `max_tokens`
3. Enable `debug=True` to see LLM response
4. Simplify your model (fewer fields)

### Validation Errors

If Pydantic validation fails:
1. Check field types match expected data
2. Review LLM response in debug logs
3. Add field descriptions to guide LLM
4. Use Pydantic validators for constraints

### API Errors

```python
from pydantic_llm_mixin import GroqClientError

try:
    person = await Person.generate_instance(...)
except GroqClientError as e:
    print(f"API error: {e}")
    # Check API key, network, Groq status
```

## Next Steps

- Read the [full README](README.md) for advanced features
- Check [ARCHITECTURE.md](ARCHITECTURE.md) for design details
- See [examples/](examples/) for more examples
- Read [CONTRIBUTING.md](CONTRIBUTING.md) to contribute

## Common Questions

**Q: Can I use this with OpenAI/Claude?**
A: Currently Groq only. Other providers can be added (see CONTRIBUTING.md).

**Q: Is there a synchronous version?**
A: No, async/await only. Use `asyncio.run()` for sync contexts.

**Q: Can I cache responses?**
A: Not built-in. Add your own caching layer around `generate_instance()`.

**Q: How do I handle sensitive data?**
A: Don't send sensitive data to LLMs. Use synthetic examples or sanitize inputs.

**Q: Can I fine-tune the prompts?**
A: The package uses minimal prompting by design. Field descriptions are the spec.

## Get Help

- Open an issue on [GitHub](https://github.com/eyzaguirre-co/pydantic-llm-mixin)
- Check existing issues for solutions
- Read the docs thoroughly first

Happy generating! 🚀
