# Social Media Pulse Page - Step-by-Step Guide

A comprehensive tutorial on building complex Pydantic models with LLM-powered generation using `pydantic-llm-mixin`.

## 📋 What We're Building

A social media analytics dashboard that aggregates:
- 📊 Trending topics and hashtags
- 📱 Featured posts (text, images, videos, polls)
- 💬 Engagement metrics
- 👥 Audience demographics
- 💡 AI-generated insights

All automatically generated from natural language using LLM!

## 🎯 Key Concepts You'll Learn

1. **Discriminated Unions** - Multiple content types (TextPost | ImagePost | VideoPost | PollPost)
2. **Nested Models** - Complex hierarchical data structures
3. **Type-Safe Validation** - Pydantic ensures data integrity
4. **GenerativeMixin** - LLM-powered instance generation
5. **FastAPI Integration** - Production-ready API deployment

---

## 📚 Step-by-Step Tutorial

### Step 1: Define Content Type Models (Discriminated Union Members)

Start by defining the different types of content your pulse page will support. Each type is a separate Pydantic model.

```python
from pydantic import BaseModel, Field
from typing import Literal

class TextPost(BaseModel):
    """A text-based social media post"""
    content: str = Field(..., description="The text content of the post")
    hashtags: list[str] = Field(..., description="Hashtags used in the post")
    mentions: int = Field(..., description="Number of user mentions")
    word_count: int = Field(..., description="Number of words in the post")

class ImagePost(BaseModel):
    """An image-based social media post"""
    caption: str = Field(..., description="Image caption")
    image_description: str = Field(..., description="Description of what the image shows")
    filters_used: list[str] = Field(..., description="Photo filters applied")
    resolution: str = Field(..., description="Image resolution (e.g., '1080x1080')")

class VideoPost(BaseModel):
    """A video social media post"""
    title: str = Field(..., description="Video title")
    description: str = Field(..., description="Video description")
    duration_seconds: int = Field(..., description="Video length in seconds")
    video_quality: Literal["480p", "720p", "1080p", "4K"] = Field(..., description="Video quality")
    has_subtitles: bool = Field(..., description="Whether video has subtitles")

class PollPost(BaseModel):
    """A poll post"""
    question: str = Field(..., description="Poll question")
    options: list[str] = Field(..., description="Poll options (2-4 choices)")
    duration_hours: int = Field(..., description="How long the poll runs in hours")
    allows_multiple_choices: bool = Field(..., description="Can users select multiple options")
```

**Why This Works:**
- Each model represents a distinct content type
- Rich field descriptions help the LLM understand what to generate
- `Literal` types constrain values to valid options

---

### Step 2: Create a Discriminated Union

Combine all content types into a single union type. Pydantic will automatically determine which type to use based on the data.

```python
# This is the magic - Pydantic automatically figures out the correct type!
SocialMediaContent = TextPost | ImagePost | VideoPost | PollPost
```

**Why This Works:**
- No explicit discriminator field needed
- Pydantic inspects field names and types to determine the correct model
- LLM generates data that matches one of the union members

---

### Step 3: Define Supporting Models

Create models for metrics and other nested data structures.

```python
class EngagementMetrics(BaseModel):
    """Engagement metrics for a post"""
    likes: int = Field(..., description="Number of likes")
    comments: int = Field(..., description="Number of comments")
    shares: int = Field(..., description="Number of shares")
    saves: int = Field(..., description="Number of saves/bookmarks")
    views: int = Field(..., description="Number of views")

class AudienceDemographics(BaseModel):
    """Demographics of engaged audience"""
    age_group: Literal["13-17", "18-24", "25-34", "35-44", "45-54", "55+"] = Field(
        ..., description="Primary age group"
    )
    gender_distribution: dict[str, float] = Field(
        ..., description="Gender distribution percentages (e.g., {'male': 45.5, 'female': 54.5})"
    )
    top_locations: list[str] = Field(..., description="Top 3 geographic locations")
```

**Best Practices:**
- Use descriptive field names
- Add detailed descriptions for the LLM
- Use appropriate Python types (int, float, list, dict)

---

### Step 4: Create Individual Post Model

Combine your content union with metadata.

```python
class SocialMediaPost(BaseModel):
    """A single social media post with all metadata"""
    post_id: str = Field(..., description="Unique post identifier")
    platform: Literal["Instagram", "Twitter", "Facebook", "TikTok", "LinkedIn"] = Field(
        ..., description="Social media platform"
    )
    author_username: str = Field(..., description="Username of the post author")
    posted_at: str = Field(..., description="When the post was published (ISO 8601 format)")

    # This field uses our discriminated union!
    content: SocialMediaContent = Field(..., description="The actual post content")

    engagement: EngagementMetrics = Field(..., description="Engagement statistics")
    is_sponsored: bool = Field(..., description="Whether this is a sponsored/promoted post")
    sentiment: Literal["positive", "neutral", "negative"] = Field(..., description="Overall sentiment")
```

**Key Points:**
- The `content` field accepts any of our content types
- Nested models (EngagementMetrics) are automatically handled
- Literal types ensure valid values

---

### Step 5: Create Trending Topic Model

Define additional supporting models as needed.

```python
class TrendingTopic(BaseModel):
    """A trending topic or hashtag"""
    topic: str = Field(..., description="The trending topic or hashtag")
    post_count: int = Field(..., description="Number of posts about this topic")
    growth_rate: float = Field(..., description="Growth rate as percentage (e.g., 150.5 for 150.5% growth)")
    category: Literal["news", "entertainment", "sports", "technology", "lifestyle", "politics"] = Field(
        ..., description="Category of the trend"
    )
```

---

### Step 6: Create the Main Model with GenerativeMixin

This is where the magic happens! Add `GenerativeMixin` to enable LLM generation.

```python
from pydantic_llm_mixin import GenerativeMixin

class SocialMediaPulse(BaseModel, GenerativeMixin):
    """
    A comprehensive social media pulse page.

    This is the main model that inherits from GenerativeMixin.
    """
    page_title: str = Field(..., description="Title of the pulse page")
    time_period: str = Field(..., description="Time period covered (e.g., 'Last 24 hours')")
    total_posts_analyzed: int = Field(..., description="Total number of posts analyzed")
    overall_engagement_rate: float = Field(..., description="Overall engagement rate as percentage")

    trending_topics: list[TrendingTopic] = Field(
        ...,
        description="List of 3-5 trending topics",
        min_length=3,
        max_length=5
    )

    featured_posts: list[SocialMediaPost] = Field(
        ...,
        description="Top performing posts (5-10 posts)",
        min_length=5,
        max_length=10
    )

    audience_demographics: AudienceDemographics = Field(
        ...,
        description="Overall audience demographics"
    )

    key_insights: list[str] = Field(
        ...,
        description="3-5 key insights from the data",
        min_length=3,
        max_length=5
    )
```

**Critical Details:**
- **Only the top-level model** needs `GenerativeMixin`
- Use `min_length` and `max_length` to constrain list sizes
- Nested models work automatically

---

### Step 7: Generate Instances with LLM

Now use the `generate_instance()` method to create data from natural language.

```python
import asyncio
import os
from pydantic_llm_mixin import get_groq_client

async def main():
    # Initialize the Groq client
    api_key = os.getenv("GROQ_API_KEY")
    client = await get_groq_client(api_key=api_key, temperature=0.7, max_tokens=4000)

    # Create a conversation with your query
    conversation = [
        {
            "role": "user",
            "content": """Create a social media pulse page for a tech startup's
            content from the last 24 hours. Include a mix of text posts, image posts,
            video posts, and at least one poll. Show trending topics related to AI,
            startups, and technology."""
        }
    ]

    # Generate the pulse page - this is where the magic happens!
    pulse = await SocialMediaPulse.generate_instance(
        client=client,
        conversation_history=conversation,
        debug=True  # Set to True to see raw LLM response
    )

    # Access the structured data
    print(f"Title: {pulse.page_title}")
    print(f"Total Posts: {pulse.total_posts_analyzed}")

    for topic in pulse.trending_topics:
        print(f"Trending: #{topic.topic} ({topic.post_count} posts)")

    for post in pulse.featured_posts:
        if isinstance(post.content, TextPost):
            print(f"Text: {post.content.content}")
        elif isinstance(post.content, VideoPost):
            print(f"Video: {post.content.title}")

    # Clean up
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

**What Happens:**
1. LLM receives your query + the Pydantic schema
2. LLM generates JSON matching the schema
3. `pydantic-llm-mixin` extracts and validates the JSON
4. You get a fully validated `SocialMediaPulse` instance!

---

### Step 8: Add to FastAPI (Production Ready)

Create a REST API endpoint for your generator.

```python
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic_llm_mixin import GenerationError

groq_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global groq_client
    api_key = os.getenv("GROQ_API_KEY")
    groq_client = await get_groq_client(api_key=api_key, temperature=0.7, max_tokens=4000)
    yield
    if groq_client:
        await groq_client.close()

app = FastAPI(title="Social Media Pulse API", lifespan=lifespan)

class GenerateRequest(BaseModel):
    query: str = Field(..., description="Describe the pulse page you want")

@app.post("/generate")
async def generate_pulse(request: GenerateRequest):
    try:
        conversation = [{"role": "user", "content": request.query}]

        pulse = await SocialMediaPulse.generate_instance(
            client=groq_client,
            conversation_history=conversation
        )

        return {"pulse": pulse, "success": True}

    except GenerationError as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
```

---

## 🚀 Running the Examples

### Option 1: Basic Script

```bash
# Set your API key
export GROQ_API_KEY="gsk_your_key_here"

# Run the example
python examples/social_media_pulse.py
```

### Option 2: Use Railway Variables (Recommended)

```bash
# Railway automatically loads environment variables
railway run python examples/social_media_pulse.py
```

### Option 3: FastAPI Server

```bash
# Run locally
railway run uvicorn examples.social_media_pulse_api:app --reload --port 8200

# Test with curl
curl -X POST http://localhost:8200/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "Create a tech startup pulse page from last 24 hours"}'
```

---

## 💡 Pro Tips

### 1. **Field Descriptions Are Critical**
The LLM uses field descriptions to understand what to generate. Be specific!

❌ Bad:
```python
name: str = Field(..., description="Name")
```

✅ Good:
```python
name: str = Field(..., description="Full name of the social media account owner")
```

### 2. **Use Literal Types for Constraints**
Guide the LLM to valid values:

```python
platform: Literal["Instagram", "Twitter", "Facebook", "TikTok", "LinkedIn"]
```

### 3. **Set Reasonable Limits**
Prevent the LLM from generating too much data:

```python
featured_posts: list[SocialMediaPost] = Field(..., min_length=5, max_length=10)
```

### 4. **Nested Models Work Automatically**
No special handling needed - just use them:

```python
engagement: EngagementMetrics  # Automatically parsed!
```

### 5. **Debug Mode Shows Raw Response**
Use `debug=True` to see what the LLM actually generated:

```python
pulse = await SocialMediaPulse.generate_instance(
    client=client,
    conversation_history=conversation,
    debug=True  # Shows raw LLM output
)
```

### 6. **Discriminated Unions Are Powerful**
Let Pydantic figure out the type:

```python
content: TextPost | ImagePost | VideoPost | PollPost

# Later, check the type:
if isinstance(post.content, VideoPost):
    print(f"Duration: {post.content.duration_seconds}s")
```

---

## 🎨 Customization Ideas

### Add More Post Types
```python
class StoryPost(BaseModel):
    """An ephemeral story post (24-hour expiry)"""
    media_type: Literal["photo", "video"]
    duration_seconds: int
    sticker_count: int
    has_music: bool

# Add to union
SocialMediaContent = TextPost | ImagePost | VideoPost | PollPost | StoryPost
```

### Add Time-Based Analytics
```python
class TimeSeriesData(BaseModel):
    """Engagement over time"""
    timestamp: str
    engagement_count: int
    sentiment_score: float

class SocialMediaPulse(BaseModel, GenerativeMixin):
    # ... existing fields ...
    hourly_engagement: list[TimeSeriesData] = Field(..., min_length=24, max_length=24)
```

### Add Competitor Analysis
```python
class CompetitorMetrics(BaseModel):
    """Competitor performance comparison"""
    competitor_name: str
    engagement_rate: float
    follower_growth: float
    top_performing_content_type: str

class SocialMediaPulse(BaseModel, GenerativeMixin):
    # ... existing fields ...
    competitor_analysis: list[CompetitorMetrics] = Field(..., max_length=5)
```

---

## 🐛 Troubleshooting

### Issue: "GROQ_API_KEY not set"
**Solution:**
```bash
export GROQ_API_KEY="gsk_your_key_here"
# Or use Railway:
railway variables --set "GROQ_API_KEY=gsk_your_key_here"
```

### Issue: Generation fails with validation error
**Solution:**
- Check your field descriptions are clear
- Use `debug=True` to see what the LLM generated
- Simplify your model if it's too complex
- Increase `max_tokens` if response is truncated

### Issue: Wrong content type in union
**Solution:**
- Make field names more distinctive between union members
- Add more specific field descriptions
- Use fewer union members if possible

---

## 📦 Files Reference

| File | Purpose |
|------|---------|
| `social_media_pulse.py` | Basic example - run standalone |
| `social_media_pulse_api.py` | FastAPI deployment - production ready |
| `SOCIAL_MEDIA_PULSE_GUIDE.md` | This guide |

---

## 🎓 What You Learned

✅ How to design complex Pydantic models with nested structures
✅ How to use discriminated unions for flexible content types
✅ How to use GenerativeMixin for LLM-powered data generation
✅ How to validate and constrain LLM outputs
✅ How to deploy as a production FastAPI service

---

## 🚀 Next Steps

1. **Modify the models** to match your use case
2. **Add custom validation** with validation callbacks
3. **Deploy to Railway** for production use
4. **Add streaming** with streaming callbacks
5. **Integrate with your database** to persist results

---

## 📚 Additional Resources

- [Pydantic Documentation](https://docs.pydantic.dev/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Groq API Documentation](https://console.groq.com/docs)
- [pydantic-llm-mixin README](../README.md)

---

**Questions or issues?** Open an issue on GitHub or check the main README.

Happy building! 🎉