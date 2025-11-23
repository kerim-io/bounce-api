# Pydantic LLM Mixin

**Turn any Pydantic model into an LLM-generated instance with robust validation**

Best-of-breed GenerativeMixin that combines:
- 🎯 **Multi-strategy JSON extraction** from LLM responses
- 🔄 **Robust retry logic** with exponential backoff
- 🏭 **Clean provider abstraction** (Groq primary, extensible)
- ✅ **Type-safe Pydantic validation** - trust the schema
- 🚀 **Discriminated unions** - automatic type detection

## Quick Example

```python
from pydantic import BaseModel, Field
from pydantic_llm_mixin import GenerativeMixin, get_groq_client

class Book(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    price: float = Field(..., description="Price in dollars")

class Bookstore(BaseModel, GenerativeMixin):
    name: str = Field(..., description="Bookstore name")
    location: str = Field(..., description="City and country")
    inventory: list[Book] = Field(..., description="Books in stock")

async def main():
    client = await get_groq_client(api_key="your-groq-api-key")

    bookstore = await Bookstore.generate_instance(
        client=client,
        conversation_history=[{"role": "user", "content": "Create a bookstore in Paris"}]
    )

    print(f"{bookstore.name} in {bookstore.location}")
    for book in bookstore.inventory:
        print(f"  - {book.title} by {book.author}: ${book.price}")
```

## Prerequisites

### 1. Get Your GitHub Token (Required for Private Repo)

**IMPORTANT: Get your token FIRST before trying to install**

1. Visit [GitHub Personal Access Tokens (Classic)](https://github.com/settings/tokens)
2. Click "Generate new token" → "Generate new token (classic)"
3. Select scopes:
   - ✅ **repo** (Full control of private repositories)
4. Click "Generate token" at bottom
5. **Copy the token immediately** (you won't see it again!)
6. Save it:
   ```bash
   export GITHUB_TOKEN="ghp_your_token_here"
   ```

### 2. Get Your Groq API Key (Required)

1. Visit [Groq Console](https://console.groq.com/home)
2. Sign up for a free account
3. Navigate to API Keys section
4. Generate a new API key
5. Save your key:
   ```bash
   export GROQ_API_KEY="gsk_your_key_here"
   ```

**Free tier includes:**
- 30 requests/minute
- 14,400 requests/day
- Access to reasoning models (DeepSeek, GPT-OSS, Qwen)

### 3. Set Up Railway (Required for Deployment)

1. Visit [Railway](https://railway.com?referralCode=d3k_vU)
2. Sign up/login with GitHub
3. Install Railway CLI:
   ```bash
   npm i -g @railway/cli
   ```
4. Login to Railway CLI:
   ```bash
   railway login
   ```
5. Link your project:
   ```bash
   cd /path/to/pydantic-llm-mixin
   railway link
   ```
6. Set environment variables:
   ```bash
   railway variables set GROQ_API_KEY="gsk_your_key_here"
   ```

**Verify Railway setup:**
```bash
railway variables
# Should show GROQ_API_KEY=gsk_...
```

## Installation

### From Private GitHub Repository

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Add to your pyproject.toml
[project]
dependencies = ["pydantic-llm-mixin"]

[tool.uv.sources]
pydantic-llm-mixin = { git = "https://github.com/aceeyz/pydantic-llm-mixin.git", branch = "main" }

# Install
uv sync
```

## Development Setup

### Clone and Install

```bash
# Clone repository
git clone https://github.com/aceeyz/pydantic-llm-mixin.git
cd pydantic-llm-mixin

# Install dependencies (uses uv)
make install-dev
```

### Makefile Commands

#### Development

```bash
make install-dev       # Install package with dev dependencies
make test              # Run tests
make test-verbose      # Run tests with verbose output
make lint              # Run linters (ruff)
make lint-fix          # Auto-fix linting issues
make type-check        # Run type checker (ty)
make quality           # Run all quality checks (lint + type)
make clean             # Remove build artifacts
```

#### Railway Deployment

```bash
make railway-local     # Run FastAPI locally with Railway env vars
make railway-docker    # Run FastAPI in Docker with Railway env vars
make railway-stop      # Stop Docker container
make railway-build     # Build Docker image with Railway env vars
make deploy-railway    # Deploy to Railway (git push)
```

**Important:** All `railway-*` commands require Railway CLI setup (see Prerequisites #3)

#### Example Workflow

```bash
# 1. Install and run quality checks
make install-dev
make quality

# 2. Test locally (no Docker)
make railway-local
# Visit http://localhost:8200

# 3. Test in Docker
make railway-build      # Build image
make railway-docker     # Run container
# Visit http://localhost:8200
make railway-stop       # Stop when done

# 4. Deploy to production
make deploy-railway
```

## Examples

### Discriminated Unions (Masterclass)

The mixin automatically handles discriminated unions - no explicit discriminator field needed!

```python
from typing import Literal
from pydantic import BaseModel, Field
from pydantic_llm_mixin import GenerativeMixin

class Book(BaseModel):
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    isbn: str = Field(..., description="ISBN")
    price: float = Field(..., description="Price in dollars")
    pages: int = Field(..., description="Number of pages")

class DVD(BaseModel):
    title: str = Field(..., description="DVD title")
    director: str = Field(..., description="Director")
    runtime_minutes: int = Field(..., description="Runtime in minutes")
    price: float = Field(..., description="Price in dollars")
    rating: Literal["G", "PG", "PG-13", "R", "NC-17"] = Field(..., description="Rating")

class Poster(BaseModel):
    title: str = Field(..., description="Poster title")
    artist: str = Field(..., description="Artist")
    dimensions: str = Field(..., description="Dimensions like '24x36 inches'")
    price: float = Field(..., description="Price in dollars")
    material: Literal["paper", "canvas", "vinyl"] = Field(..., description="Material")

# Discriminated union - Pydantic figures it out automatically!
BookstoreItem = Book | DVD | Poster

class Bookstore(BaseModel, GenerativeMixin):
    name: str = Field(..., description="Bookstore name")
    location: str = Field(..., description="City and country")
    specialty: str = Field(..., description="What the store specializes in")
    inventory: list[BookstoreItem] = Field(..., description="Items in stock")

# LLM automatically generates correct types!
bookstore = await Bookstore.generate_instance(
    client=client,
    conversation_history=[{"role": "user", "content": "Create a bookstore in Paris"}]
)

# Result: Mix of Books, DVDs, and Posters
for item in bookstore.inventory:
    if isinstance(item, Book):
        print(f"Book: {item.title} by {item.author}")
    elif isinstance(item, DVD):
        print(f"DVD: {item.title} directed by {item.director}")
    elif isinstance(item, Poster):
        print(f"Poster: {item.title} by {item.artist}")
```

See `examples/railway_deployment.py` for the complete FastAPI implementation.

### Custom Validation

```python
class MovieCast(BaseModel, GenerativeMixin):
    actors: list[str] = Field(..., description="List of main actors")
    director: str = Field(..., description="Film director")

def validate_cast_size(instance: MovieCast) -> tuple[bool, str | None]:
    if len(instance.actors) != 3:
        return False, f"Need exactly 3 actors, got {len(instance.actors)}"
    return True, None

cast = await MovieCast.generate_instance(
    client=client,
    conversation_history=[{"role": "user", "content": "The Matrix with 3 actors"}],
    validation_callback=validate_cast_size
)
```

### Streaming Callbacks

```python
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
```

## Testing the Bookstore API

### Run Locally

```bash
# Terminal 1: Start server
make railway-local

# Terminal 2: Test endpoint
curl -X POST http://localhost:8200/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a bookstore in Paris"}'
```

### Run in Docker

```bash
# Build and run
make railway-build
make railway-docker

# Test
curl -X POST http://localhost:8200/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a bookstore in Tokyo specializing in manga"}'

# Stop
make railway-stop
```

### Deploy to Railway

```bash
# Commit your changes
git add .
git commit -m "feat: Add bookstore example"
git push origin main

# Deploy
make deploy-railway

# Test production
curl -X POST https://your-app.railway.app/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a bookstore in London"}'
```

## Docker Configuration

The project includes a production-ready Dockerfile:

- **Base**: Python 3.11-slim
- **Package manager**: UV (fast Python package installer)
- **Runtime**: FastAPI + Uvicorn with hot reload
- **Security**: Runs as non-root user (appuser)
- **Environment**: Passes Railway env vars (GROQ_API_KEY, PORT)

Build args:
```dockerfile
ARG GROQ_API_KEY  # Groq API key from Railway
ARG PORT=8200     # Server port
```

## Railway Deployment Architecture

```
┌─────────────────────────────────────────┐
│          Railway Platform               │
├─────────────────────────────────────────┤
│  Environment Variables                  │
│  - GROQ_API_KEY (set in dashboard)     │
│  - PORT (auto-injected)                 │
│  - GITHUB_TOKEN (auto-injected)         │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│         Docker Container                │
├─────────────────────────────────────────┤
│  ┌─────────────────────────────────┐   │
│  │  FastAPI Server (port 8200)     │   │
│  │  - /generate endpoint           │   │
│  │  - Bookstore discriminated      │   │
│  │    union example                │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  pydantic-llm-mixin             │   │
│  │  - GenerativeMixin              │   │
│  │  - GroqClient                   │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## Railway Configuration Files

### railway.json

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "dockerfile",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "startCommand": "uv run uvicorn examples.railway_deployment:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "on_failure",
    "restartPolicyMaxRetries": 10,
    "healthcheckPath": "/",
    "healthcheckTimeout": 100
  }
}
```

### railway.toml

```toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "uv run uvicorn examples.railway_deployment:app --host 0.0.0.0 --port $PORT"
```

## Environment Variables Reference

| Variable | Required | Where | Description |
|----------|----------|-------|-------------|
| `GROQ_API_KEY` | ✅ | Local, Railway | Groq API key for LLM inference |
| `GITHUB_TOKEN` | ✅ | Local | GitHub personal access token (classic) for private repo access |
| `PORT` | ⚠️ | Railway | Server port (auto-injected by Railway, default 8200 locally) |

**Local .env file:**
```bash
GROQ_API_KEY=gsk_your_key_here
GITHUB_TOKEN=ghp_your_token_here
PORT=8200
```

**Railway dashboard:**
- Set `GROQ_API_KEY` manually
- `PORT` and `GITHUB_TOKEN` are auto-injected

## Supported Models

```python
from pydantic_llm_mixin import GroqModel

# Available models
GroqModel.OPENAI_GPT_OSS_120B  # Default - best for complex reasoning
GroqModel.OPENAI_GPT_OSS_20B   # Faster, smaller model
GroqModel.DEEPSEEK_R1_DISTILL_LLAMA_70B  # DeepSeek reasoning
GroqModel.QWEN3_32B  # Qwen reasoning model
GroqModel.GROQ_COMPOUND  # Compound AI with built-in tools
GroqModel.GROQ_COMPOUND_MINI  # Smaller compound system
```

## Error Handling

```python
from pydantic_llm_mixin import GenerationError

try:
    bookstore = await Bookstore.generate_instance(
        client=client,
        conversation_history=conversation,
        max_retries=3
    )
except GenerationError as e:
    print(f"Generation failed: {e}")
```

**Retry behavior:**
- Transient LLM errors: Retry with exponential backoff
- JSON parsing errors: Retry with base delay
- Validation errors: Retry with base delay
- Non-transient errors: Fail immediately

## Troubleshooting

### Railway CLI not found
```bash
npm i -g @railway/cli
railway login
```

### Docker build fails
```bash
make railway-build  # Uses Railway env vars automatically
```

### FastAPI won't start in Docker
```bash
# Check logs
docker logs bookstore-test

# Stop and rebuild
make railway-stop
make railway-build
make railway-docker
```

### Rate limiting errors
```bash
# Check Groq dashboard for quota
# Free tier: 30 req/min, 14,400 req/day
```

## License

MIT License - see LICENSE file for details.

## Credits

Built by [Alan Eyzaguirre](https://eyzaguirre.co) at Eyzaguirre.co.

Combines best-of-breed patterns from:
- **mari-pydantic-orm** - Authentication context and robust error handling
- **mari-agentic-llm** - Clean provider abstraction
- **fast_spacy** - Multi-strategy JSON extraction

## Contributing

Contributions welcome! Please open an issue or PR on GitHub.
