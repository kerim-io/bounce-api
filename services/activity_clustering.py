"""
Activity Clustering Service

Aggregates post locations into anonymized clusters for the map view.
Shows "X people here" without revealing usernames.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from dataclasses import dataclass
from collections import Counter
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import Post
from services.geofence import haversine_distance
from core.config import settings


@dataclass
class ActivityCluster:
    """A cluster of nearby post activity"""
    cluster_id: str
    latitude: float
    longitude: float
    count: int  # Number of unique users
    venue_name: Optional[str]
    last_activity: datetime


def generate_cluster_id(lat: float, lon: float) -> str:
    """Generate a consistent cluster ID from coordinates"""
    # Round to ~10m precision for stable IDs
    rounded = f"{lat:.4f},{lon:.4f}"
    return hashlib.md5(rounded.encode()).hexdigest()[:12]


async def get_activity_clusters(
    db: AsyncSession,
    time_window_minutes: Optional[int] = None,
    cluster_radius_meters: Optional[float] = None
) -> List[ActivityCluster]:
    """
    Get clustered post activity for the map.

    Args:
        db: Database session
        time_window_minutes: How far back to look (default from config)
        cluster_radius_meters: Clustering radius in meters (default from config)

    Returns:
        List of ActivityCluster objects with unique user counts
    """
    if time_window_minutes is None:
        time_window_minutes = settings.ACTIVITY_TIME_WINDOW_MIN
    if cluster_radius_meters is None:
        cluster_radius_meters = settings.ACTIVITY_CLUSTER_RADIUS_M

    # Convert meters to kilometers for haversine
    cluster_radius_km = cluster_radius_meters / 1000.0

    # Calculate time threshold
    time_threshold = datetime.now(timezone.utc) - timedelta(minutes=time_window_minutes)

    # Query posts with location from the time window
    result = await db.execute(
        select(Post)
        .where(
            Post.created_at >= time_threshold,
            Post.latitude.isnot(None),
            Post.longitude.isnot(None)
        )
        .order_by(Post.created_at.desc())
    )
    posts = result.scalars().all()

    if not posts:
        return []

    # Greedy clustering algorithm
    # Track: cluster centers, user sets per cluster, venue names, last activity
    clusters: List[dict] = []

    for post in posts:
        post_lat = post.latitude
        post_lon = post.longitude
        user_id = post.user_id
        venue_name = post.venue_name
        created_at = post.created_at

        # Find if this post belongs to an existing cluster
        found_cluster = None
        for cluster in clusters:
            distance_km = haversine_distance(
                cluster["latitude"],
                cluster["longitude"],
                post_lat,
                post_lon
            )
            if distance_km <= cluster_radius_km:
                found_cluster = cluster
                break

        if found_cluster:
            # Add user to existing cluster
            found_cluster["user_ids"].add(user_id)
            if venue_name:
                found_cluster["venue_names"].append(venue_name)
            # Update last activity if this post is newer
            if created_at > found_cluster["last_activity"]:
                found_cluster["last_activity"] = created_at
        else:
            # Create new cluster with this post as center
            clusters.append({
                "latitude": post_lat,
                "longitude": post_lon,
                "user_ids": {user_id},
                "venue_names": [venue_name] if venue_name else [],
                "last_activity": created_at
            })

    # Convert to ActivityCluster objects
    result_clusters = []
    for cluster in clusters:
        # Get most common venue name (if any)
        venue_name = None
        if cluster["venue_names"]:
            venue_counter = Counter(cluster["venue_names"])
            venue_name = venue_counter.most_common(1)[0][0]

        result_clusters.append(ActivityCluster(
            cluster_id=generate_cluster_id(cluster["latitude"], cluster["longitude"]),
            latitude=cluster["latitude"],
            longitude=cluster["longitude"],
            count=len(cluster["user_ids"]),
            venue_name=venue_name,
            last_activity=cluster["last_activity"]
        ))

    # Sort by count descending (busiest first)
    result_clusters.sort(key=lambda c: c.count, reverse=True)

    return result_clusters
