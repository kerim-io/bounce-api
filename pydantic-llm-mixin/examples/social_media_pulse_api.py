"""
Social Media Pulse API - FastAPI Deployment Example

A production-ready FastAPI application that generates social media pulse pages
using GenerativeMixin.

Deploy to Railway:
  1. Set GROQ_API_KEY in Railway dashboard
  2. Update railway.json startCommand to point to this file
  3. git push origin main
"""

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerationError, GenerativeMixin, get_groq_client

# Global client
groq_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown"""
    global groq_client

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set - get one at https://console.groq.com/keys")

    groq_client = await get_groq_client(api_key=api_key, temperature=0.7, max_tokens=4000)
    print("✅ Groq client initialized for Social Media Pulse API")

    yield

    if groq_client:
        await groq_client.close()
        print("✅ Groq client closed")


app = FastAPI(
    title="Social Media Pulse API",
    description="Generate social media analytics dashboards using LLM-powered structured data generation",
    version="1.0.0",
    lifespan=lifespan
)


# ============================================================================
# MODELS (Same as social_media_pulse.py)
# ============================================================================


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


SocialMediaContent = TextPost | ImagePost | VideoPost | PollPost


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
        ..., description="Gender distribution percentages"
    )
    top_locations: list[str] = Field(..., description="Top 3 geographic locations")


class SocialMediaPost(BaseModel):
    """A single social media post with all metadata"""
    post_id: str = Field(..., description="Unique post identifier")
    platform: Literal["Instagram", "Twitter", "Facebook", "TikTok", "LinkedIn"] = Field(
        ..., description="Social media platform"
    )
    author_username: str = Field(..., description="Username of the post author")
    posted_at: str = Field(..., description="When the post was published (ISO 8601 format)")
    content: SocialMediaContent = Field(..., description="The actual post content")
    engagement: EngagementMetrics = Field(..., description="Engagement statistics")
    is_sponsored: bool = Field(..., description="Whether this is a sponsored/promoted post")
    sentiment: Literal["positive", "neutral", "negative"] = Field(..., description="Overall sentiment")


class TrendingTopic(BaseModel):
    """A trending topic or hashtag"""
    topic: str = Field(..., description="The trending topic or hashtag")
    post_count: int = Field(..., description="Number of posts about this topic")
    growth_rate: float = Field(..., description="Growth rate as percentage")
    category: Literal["news", "entertainment", "sports", "technology", "lifestyle", "politics"] = Field(
        ..., description="Category of the trend"
    )


class SocialMediaPulse(BaseModel, GenerativeMixin):
    """A comprehensive social media pulse page"""
    page_title: str = Field(..., description="Title of the pulse page")
    time_period: str = Field(..., description="Time period covered")
    total_posts_analyzed: int = Field(..., description="Total number of posts analyzed")
    overall_engagement_rate: float = Field(..., description="Overall engagement rate as percentage")
    trending_topics: list[TrendingTopic] = Field(..., min_length=3, max_length=5)
    featured_posts: list[SocialMediaPost] = Field(..., min_length=5, max_length=10)
    audience_demographics: AudienceDemographics = Field(..., description="Overall audience demographics")
    key_insights: list[str] = Field(..., min_length=3, max_length=5)


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class GeneratePulseRequest(BaseModel):
    """Request to generate a social media pulse page"""
    query: str = Field(
        ...,
        description="Describe the type of pulse page you want",
        examples=[
            "Create a pulse page for a tech startup's content from last 24 hours",
            "Generate a pulse page for fashion brand content from this week",
            "Show me trending fitness content from the past 3 days"
        ]
    )
    debug: bool = Field(
        default=False,
        description="Include raw LLM response in output for debugging"
    )


class GeneratePulseResponse(BaseModel):
    """Response with generated pulse page"""
    pulse: SocialMediaPulse
    success: bool = True
    message: str = "Pulse page generated successfully"


# ============================================================================
# ENDPOINTS
# ============================================================================


@app.get("/")
async def root():
    """Health check and API info"""
    return {
        "status": "healthy",
        "service": "Social Media Pulse API",
        "version": "1.0.0",
        "endpoints": {
            "generate": "/generate - Generate a social media pulse page",
            "docs": "/docs - Interactive API documentation",
            "health": "/ - This health check"
        }
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "groq_client": "initialized" if groq_client else "not initialized"
    }


@app.post("/generate", response_model=GeneratePulseResponse)
async def generate_pulse(request: GeneratePulseRequest):
    """
    Generate a social media pulse page from natural language.

    This endpoint uses LLM-powered structured data generation to create
    a complete social media analytics dashboard based on your query.

    Example requests:
    - "Create a pulse page for a tech startup's content from last 24 hours"
    - "Generate a pulse page for fashion brand content from this week"
    - "Show me trending fitness content from the past 3 days"

    The generated pulse page includes:
    - Trending topics and hashtags
    - Featured posts (mix of text, images, videos, and polls)
    - Engagement metrics
    - Audience demographics
    - Key insights
    """
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")

    try:
        conversation = [{"role": "user", "content": request.query}]

        pulse = await SocialMediaPulse.generate_instance(
            client=groq_client,
            conversation_history=conversation,
            debug=request.debug
        )

        return GeneratePulseResponse(
            pulse=pulse,
            message=f"Generated pulse page with {len(pulse.featured_posts)} posts and {len(pulse.trending_topics)} trends"
        )

    except GenerationError as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.get("/examples")
async def get_examples():
    """Get example queries for generating pulse pages"""
    return {
        "examples": [
            {
                "category": "Tech Startup",
                "query": "Create a pulse page for a tech startup's AI product launch content from the last 24 hours"
            },
            {
                "category": "Fashion Brand",
                "query": "Generate a pulse page for a luxury fashion brand's spring collection from this week"
            },
            {
                "category": "Fitness Influencer",
                "query": "Show me trending fitness and wellness content from the past 3 days"
            },
            {
                "category": "Food & Restaurant",
                "query": "Create a pulse page for a restaurant chain's promotional content from this month"
            },
            {
                "category": "Gaming",
                "query": "Generate a pulse page for gaming community content about the latest AAA game release"
            }
        ]
    }


# ============================================================================
# MAIN (for local testing)
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8200))

    print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                   SOCIAL MEDIA PULSE API - Starting...                       ║
║                                                                              ║
║  Local URL: http://localhost:{port}                                      ║
║  API Docs:  http://localhost:{port}/docs                                 ║
║  Health:    http://localhost:{port}/health                               ║
║                                                                              ║
║  Example curl:                                                              ║
║  curl -X POST http://localhost:{port}/generate \\                        ║
║    -H "Content-Type: application/json" \\                                  ║
║    -d '{{"query": "Tech startup pulse from last 24h"}}'                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "social_media_pulse_api:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )