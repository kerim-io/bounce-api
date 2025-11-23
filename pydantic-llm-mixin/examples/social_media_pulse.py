"""
Social Media Pulse Page - Basic Usage Example

This example demonstrates how to create a complex social media analytics dashboard
using GenerativeMixin with discriminated unions for different post types.

Step-by-step guide to creating your own complex Pydantic models with LLM generation.
"""

import asyncio
import os
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from pydantic_llm_mixin import GenerativeMixin, get_groq_client


# ============================================================================
# STEP 1: Define your content type models (discriminated union members)
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


# ============================================================================
# STEP 2: Create a discriminated union of your content types
# ============================================================================

SocialMediaContent = TextPost | ImagePost | VideoPost | PollPost


# ============================================================================
# STEP 3: Define supporting models for metrics and engagement
# ============================================================================


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


# ============================================================================
# STEP 4: Create individual post model that uses your content union
# ============================================================================


class SocialMediaPost(BaseModel):
    """A single social media post with all metadata"""

    post_id: str = Field(..., description="Unique post identifier")
    platform: Literal["Instagram", "Twitter", "Facebook", "TikTok", "LinkedIn"] = Field(
        ..., description="Social media platform"
    )
    author_username: str = Field(..., description="Username of the post author")
    posted_at: str = Field(..., description="When the post was published (ISO 8601 format)")
    content: SocialMediaContent = Field(..., description="The actual post content (text, image, video, or poll)")
    engagement: EngagementMetrics = Field(..., description="Engagement statistics")
    is_sponsored: bool = Field(..., description="Whether this is a sponsored/promoted post")
    sentiment: Literal["positive", "neutral", "negative"] = Field(..., description="Overall sentiment of engagement")


# ============================================================================
# STEP 5: Create trending topic model
# ============================================================================


class TrendingTopic(BaseModel):
    """A trending topic or hashtag"""

    topic: str = Field(..., description="The trending topic or hashtag")
    post_count: int = Field(..., description="Number of posts about this topic")
    growth_rate: float = Field(..., description="Growth rate as percentage (e.g., 150.5 for 150.5% growth)")
    category: Literal["news", "entertainment", "sports", "technology", "lifestyle", "politics"] = Field(
        ..., description="Category of the trend"
    )


# ============================================================================
# STEP 6: Create the main aggregator model with GenerativeMixin
# ============================================================================


class SocialMediaPulse(BaseModel, GenerativeMixin):
    """
    A comprehensive social media pulse page showing trending content and metrics.

    This is the main model that inherits from GenerativeMixin, allowing it to be
    generated from LLM responses.
    """

    page_title: str = Field(..., description="Title of the pulse page")
    time_period: str = Field(..., description="Time period covered (e.g., 'Last 24 hours', 'This week')")
    total_posts_analyzed: int = Field(..., description="Total number of posts analyzed")
    overall_engagement_rate: float = Field(..., description="Overall engagement rate as percentage")

    trending_topics: list[TrendingTopic] = Field(
        ..., description="List of 3-5 trending topics", min_length=3, max_length=5
    )

    featured_posts: list[SocialMediaPost] = Field(
        ..., description="Top performing posts (5-10 posts)", min_length=5, max_length=10
    )

    audience_demographics: AudienceDemographics = Field(..., description="Overall audience demographics")

    key_insights: list[str] = Field(
        ..., description="3-5 key insights from the data", min_length=3, max_length=5
    )


# ============================================================================
# STEP 7: Create helper functions to display the data nicely
# ============================================================================


def display_post(post: SocialMediaPost, index: int):
    """Display a social media post with proper formatting"""
    print(f"\n📱 Post #{index} - {post.platform}")
    print(f"   Author: @{post.author_username}")
    print(f"   Posted: {post.posted_at}")
    print(f"   Sponsored: {'Yes' if post.is_sponsored else 'No'}")
    print(f"   Sentiment: {post.sentiment.upper()}")

    # Display content based on type
    if isinstance(post.content, TextPost):
        print(f"   Type: TEXT POST")
        print(f"   Content: {post.content.content[:100]}...")
        print(f"   Hashtags: {', '.join(post.content.hashtags)}")
    elif isinstance(post.content, ImagePost):
        print(f"   Type: IMAGE POST")
        print(f"   Caption: {post.content.caption}")
        print(f"   Image: {post.content.image_description}")
    elif isinstance(post.content, VideoPost):
        print(f"   Type: VIDEO POST")
        print(f"   Title: {post.content.title}")
        print(f"   Duration: {post.content.duration_seconds}s at {post.content.video_quality}")
    elif isinstance(post.content, PollPost):
        print(f"   Type: POLL POST")
        print(f"   Question: {post.content.question}")
        print(f"   Options: {', '.join(post.content.options)}")

    # Display engagement
    print(f"   Engagement: {post.engagement.likes:,} likes | {post.engagement.comments:,} comments | "
          f"{post.engagement.shares:,} shares | {post.engagement.views:,} views")


def display_pulse(pulse: SocialMediaPulse):
    """Display the complete social media pulse page"""
    print("\n" + "=" * 80)
    print(f"📊 {pulse.page_title}")
    print("=" * 80)
    print(f"Period: {pulse.time_period}")
    print(f"Posts Analyzed: {pulse.total_posts_analyzed:,}")
    print(f"Overall Engagement Rate: {pulse.overall_engagement_rate}%")

    print("\n🔥 TRENDING TOPICS")
    print("-" * 80)
    for i, topic in enumerate(pulse.trending_topics, 1):
        print(f"{i}. #{topic.topic} ({topic.category})")
        print(f"   {topic.post_count:,} posts | Growth: +{topic.growth_rate}%")

    print("\n⭐ FEATURED POSTS")
    print("-" * 80)
    for i, post in enumerate(pulse.featured_posts, 1):
        display_post(post, i)

    print("\n👥 AUDIENCE DEMOGRAPHICS")
    print("-" * 80)
    print(f"Primary Age Group: {pulse.audience_demographics.age_group}")
    print(f"Gender Distribution: {pulse.audience_demographics.gender_distribution}")
    print(f"Top Locations: {', '.join(pulse.audience_demographics.top_locations)}")

    print("\n💡 KEY INSIGHTS")
    print("-" * 80)
    for i, insight in enumerate(pulse.key_insights, 1):
        print(f"{i}. {insight}")

    print("\n" + "=" * 80)


# ============================================================================
# STEP 8: Create the main async function to generate the pulse page
# ============================================================================


async def main():
    """Generate a social media pulse page using LLM"""

    # Get API key from environment
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ Error: GROQ_API_KEY environment variable not set")
        print("Get your API key at: https://console.groq.com/keys")
        print("\nFor testing, you can use Railway variables:")
        print("  railway run python examples/social_media_pulse.py")
        return

    print("🚀 Initializing Groq client...")
    client = await get_groq_client(api_key=api_key, temperature=0.7, max_tokens=4000)

    # Create conversation with user query
    print("\n📝 Generating social media pulse page...")
    conversation = [
        {
            "role": "user",
            "content": """Create a social media pulse page for a tech startup's content from the last 24 hours.
            Include a mix of text posts, image posts, video posts, and at least one poll.
            Show trending topics related to AI, startups, and technology.
            Make the engagement metrics realistic and varied."""
        }
    ]

    try:
        # Generate the pulse page using GenerativeMixin
        print("⏳ Calling LLM to generate structured data...")
        pulse = await SocialMediaPulse.generate_instance(
            client=client,
            conversation_history=conversation,
            debug=True  # Set to True to see the LLM's raw response
        )

        # Display the generated pulse page
        display_pulse(pulse)

        # Show the raw JSON structure
        print("\n📋 RAW JSON STRUCTURE:")
        print("-" * 80)
        print(pulse.model_dump_json(indent=2))

    except Exception as e:
        print(f"\n❌ Error generating pulse page: {e}")
        raise

    finally:
        # Clean up
        await client.close()
        print("\n✅ Client closed")


# ============================================================================
# STEP 9: Run the example
# ============================================================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    SOCIAL MEDIA PULSE PAGE GENERATOR                         ║
║                                                                              ║
║  This example demonstrates how to build complex Pydantic models with        ║
║  GenerativeMixin for LLM-powered structured data generation.                ║
║                                                                              ║
║  Key Concepts Demonstrated:                                                 ║
║  1. Discriminated unions (TextPost | ImagePost | VideoPost | PollPost)     ║
║  2. Nested models (EngagementMetrics, AudienceDemographics)                ║
║  3. Lists of complex objects (trending_topics, featured_posts)             ║
║  4. Type-safe validation with Pydantic                                     ║
║  5. LLM-powered instance generation with GenerativeMixin                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    asyncio.run(main())