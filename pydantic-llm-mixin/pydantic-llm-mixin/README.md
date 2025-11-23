# Pydantic LLM Mixin

**Turn any Pydantic model into an LLM-generated instance with robust validation**

## Why This Exists

The current landscape of LLM-to-structured-output tools is fundamentally broken. Most solutions prioritize vendor lock-in and framework complexity over developer experience and production reliability.

### The Problem with Existing Tools

**OpenAI Agent Kit** - Vendor-locked to OpenAI's function calling API. No fallback strategies when their JSON mode fails. Forces you into their prompt engineering patterns.

**Salesforce Agentforce** - Enterprise bloat disguised as AI tooling. Requires their entire CRM ecosystem. Opaque error handling makes debugging impossible in production.

**PydanticAI** - Over-engineered abstractions that fight against Pydantic's design philosophy. Poor error handling swallows debugging information when you need it most. "Agent" patterns where simple validation would suffice.

**Instructor** - Rigid prompt templates and limited model provider support. Forces you to structure prompts their way instead of letting the schema speak for itself.

**LangChain** - Ten layers of abstraction where one would do. Every simple task requires navigating their complex class hierarchy. Production debugging is a nightmare.

**Vercel AI SDK** - JavaScript-first with Python as an afterthought. TypeScript type inference doesn't translate to Pydantic's power. Limited retry logic.

**Anthropic Prompt Caching** - Great for cost optimization, terrible for structured outputs. No built-in Pydantic support. Roll-your-own JSON extraction.

### What We Built Instead

A tool that respects how production systems actually work:

- **Trust the LLM** - Your Pydantic schema IS the specification. Field descriptions are all you need. No over-prompting, no brittle templates.
- **Fail loudly with context** - Full stack traces, comprehensive error messages, streaming debug callbacks. You see exactly what failed and why.
- **Handle real-world LLM responses** - 4-strategy JSON extraction (regex, manual parsing, brace matching, raw). Works with how LLMs actually format JSON.
- **Stay out of your way** - Just a mixin. Use it with your existing Pydantic models. No framework to learn, no vendor lock-in.
- **First-class discriminated union support** - Pydantic's most powerful feature, properly supported. LLM automatically generates correct union types without manual discriminator fields.
- **Production-grade reliability** - Exponential backoff, transient error detection, rate limiting, customizable retry logic.

This is production-hardened code extracted from real systems that serve millions of requests.

## What It Does

Best-of-breed GenerativeMixin that combines:
- 🎯 **Multi-strategy JSON extraction** - Handles all LLM response formats
- 🔄 **Robust retry logic** - Exponential backoff, transient error detection
- 🏭 **Clean provider abstraction** - Groq primary, extensible to others
- ✅ **Type-safe Pydantic validation** - Trust the schema, not brittle prompts
- 🚀 **Discriminated unions** - Automatic type detection, no manual discriminator fields
- 💥 **Fail-fast debugging** - Full stack traces when things break

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

### Complete Development Workflow

This is the full workflow for developing, testing, and deploying changes:

#### 1. Code Quality Checks

**Always run before committing:**

```bash
# Type check with ty
make type-check
# or directly: uv run ty check

# Lint with ruff
make lint
# or directly: ruff check .

# Auto-fix linting issues
make lint-fix
# or directly: ruff check --fix .

# Run everything (recommended)
make quality
```

**Fix type errors:**
```bash
# If ty check fails, fix the errors in your code
# Common issues:
# - Missing type annotations
# - Incorrect return types
# - Mismatched function signatures

uv run ty check  # Re-run until it passes
```

#### 2. Run Tests

```bash
# Run all tests
make test

# Verbose output with print statements
make test-verbose

# Run specific test file
uv run pytest tests/test_generative_mixin.py -v

# Run specific test function
uv run pytest tests/test_generative_mixin.py::test_basic_generation -v
```

#### 3. Local Development (No Docker)

```bash
# Start FastAPI server with Railway env vars
make railway-local

# Server runs on http://localhost:8200
# Auto-reloads on code changes

# Test the endpoint
curl -X POST http://localhost:8200/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a bookstore in Paris"}'

# Stop: Ctrl+C
```

#### 4. Docker Development

**Build and run in Docker:**

```bash
# Build Docker image (uses Railway env vars)
make railway-build

# Start container
make railway-docker

# Check logs
docker logs -f bookstore-test

# Test endpoint
curl -X POST http://localhost:8200/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a bookstore in Tokyo"}'

# Stop container
make railway-stop
```

**Rebuild after code changes:**

```bash
# You MUST rebuild the image after changing code
# (no volume mounts - prevents Python import issues)
make railway-stop
make railway-build
make railway-docker
```

**Docker debugging:**

```bash
# Check container status
docker ps -a

# View logs
docker logs bookstore-test

# Inspect running container
docker exec -it bookstore-test /bin/bash

# Remove all containers (clean slate)
docker rm -f $(docker ps -aq)
```

#### 5. Git Workflow

**Standard commit and push:**

```bash
# Check status
git status

# Add all changes
git add .

# Or add specific files
git add src/pydantic_llm_mixin/generative_mixin.py
git add examples/railway_deployment.py

# Commit with descriptive message
git commit -m "feat: Add support for nested discriminated unions"

# Push to main
git push origin main

# This triggers Railway deployment automatically
```

**Commit message conventions:**

```bash
git commit -m "feat: Add new feature"       # New feature
git commit -m "fix: Fix bug in JSON parser" # Bug fix
git commit -m "docs: Update README"         # Documentation
git commit -m "refactor: Simplify retry logic" # Code refactoring
git commit -m "test: Add tests for unions"  # Add tests
git commit -m "chore: Update dependencies"  # Maintenance
```

#### 6. Complete Development Cycle

**Full workflow from code change to deployment:**

```bash
# 1. Make your changes
vim src/pydantic_llm_mixin/generative_mixin.py

# 2. Run quality checks
make quality
# Fix any issues, re-run until clean

# 3. Run tests
make test
# Fix any failures

# 4. Test locally
make railway-local
# Visit http://localhost:8200 and test
# Ctrl+C to stop

# 5. Test in Docker
make railway-build
make railway-docker
# Test endpoint
make railway-stop

# 6. Commit and push
git add .
git commit -m "feat: Your feature description"
git push origin main

# 7. Deploy to Railway (automatic on push)
# Or manually: make deploy-railway

# 8. Monitor deployment
railway logs --tail 100
```

#### 7. Railway CLI Commands

**Direct Railway commands (bypasses Makefile):**

```bash
# View environment variables
railway variables

# Set new variable
railway variables set GROQ_API_KEY="gsk_new_key"

# View logs
railway logs --tail 100

# SSH into running container
railway run bash

# Run command with Railway env vars
railway run python -c "import os; print(os.getenv('GROQ_API_KEY'))"

# Deploy manually (git push also deploys)
railway up
```

### Makefile Command Reference

#### Development Commands

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

#### Railway Deployment Commands

```bash
make railway-local     # Run FastAPI locally with Railway env vars
make railway-docker    # Run FastAPI in Docker with Railway env vars
make railway-stop      # Stop Docker container
make railway-build     # Build Docker image with Railway env vars
make deploy-railway    # Deploy to Railway (git push)
```

**Important:** All `railway-*` commands require Railway CLI setup (see Prerequisites #3)

### Troubleshooting Development

**Type check fails:**
```bash
# View detailed errors
uv run ty check

# Common fixes:
# - Add type annotations to functions
# - Import types: from typing import Optional, List
# - Fix return type mismatches
```

**Tests fail:**
```bash
# Run with verbose output
make test-verbose

# Check GROQ_API_KEY is set
echo $GROQ_API_KEY

# Set it if missing
export GROQ_API_KEY="gsk_your_key"
```

**Docker won't start:**
```bash
# Check logs
docker logs bookstore-test

# Verify Railway env vars
railway variables

# Rebuild from scratch
docker rmi pydantic-llm-mixin:latest
make railway-build
```

**Railway CLI not working:**
```bash
# Re-login
railway login

# Re-link project
railway link

# Check you're linked
railway status
```

**Import errors after changes:**
```bash
# Reinstall package
make install-dev

# Or directly
uv sync --reinstall
```

## Examples

### Geocoding API with Authentication

Production-ready geocoding service with Google Maps API, JWT authentication, and email whitelist.

See [`examples/GEOCODING_README.md`](examples/GEOCODING_README.md) for complete documentation.

```bash
# Set up environment
export GOOGLE_MAPS_API_KEY="your-api-key"
export APPROVED_USERS="your@email.com"
export JWT_SECRET_KEY="your-secret-key"

# Start server
uv run uvicorn examples.geocoding_api:app --port 8200

# Login
uv run python cli.py login

# Geocode an address
uv run python cli.py geocode "Statue of Liberty, New York"

# Reverse geocode coordinates
uv run python cli.py reverse 37.422408 -122.084068
```

**Features:**
- Google Maps API for production-grade geocoding
- JWT authentication with email whitelist (`APPROVED_USERS` env var)
- Forward and reverse geocoding with rich address data
- Full Pydantic validation
- Railway deployment ready

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
  -d '{"query": "Create a bookstore in Paris"}'

# Stop
make railway-stop
```

**Example Response:**

```json
{
  "bookstore": {
    "name": "Le Livre Lumière",
    "location": "Paris, France",
    "specialty": "Classic French literature",
    "inventory": [
      {
        "title": "Les Misérables",
        "author": "Victor Hugo",
        "isbn": "978-0451419439",
        "price": 12.99,
        "pages": 1463
      },
      {
        "title": "Amélie",
        "director": "Jean-Pierre Jeunet",
        "runtime_minutes": 122,
        "price": 14.99,
        "rating": "PG"
      },
      {
        "title": "Starry Night",
        "artist": "Vincent van Gogh",
        "dimensions": "24x36 inches",
        "price": 19.99,
        "material": "canvas"
      }
    ]
  },
  "success": true
}
```

**Notice:** The LLM automatically generated the correct discriminated union types:
- ✅ **Book** - Les Misérables (has `author`, `isbn`, `pages`)
- ✅ **DVD** - Amélie (has `director`, `runtime_minutes`, `rating`)
- ✅ **Poster** - Starry Night (has `artist`, `dimensions`, `material`)

No explicit discriminator field needed!

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
