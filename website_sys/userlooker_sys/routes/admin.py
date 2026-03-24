"""
Admin routes for UserLooker.
Protected endpoints for admin dashboard and management.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from database import (
    get_known_users_collection,
    get_unknown_users_collection,
    get_rank_history_collection,
    get_rank_history_collection,
    get_audit_logs_collection,
    get_admin_sessions_collection,
    get_message_db
)
from utils.auth import get_current_admin, CurrentUser
from utils.pagination import paginate, get_pagination_params, PaginationParams, PaginatedResponse
from utils.filters import UserFilterParams, get_user_filters, build_user_query
from middleware.rate_limit import limiter

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================================================
# Response Models
# ============================================================================

class StatisticsResponse(BaseModel):
    """Dashboard statistics response."""
    known_users: int
    unknown_users: int
    total_users: int
    total_messages: int
    total_guilds: int
    rank_changes: int
    active_sessions: int
    last_extraction: Optional[datetime] = None


class TopUser(BaseModel):
    """Top user by message count."""
    roblox_username: str
    total_messages: int
    guild_count: int


class RankDistribution(BaseModel):
    """Rank distribution item."""
    rank: str
    count: int


# ============================================================================
# Statistics Endpoints
# ============================================================================

@router.get("/statistics", response_model=StatisticsResponse)
@limiter.limit("60/minute")
async def get_statistics(
    request: Request,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    Get dashboard statistics.
    
    Returns aggregate counts and metrics for the admin dashboard.
    """
    known_collection = await get_known_users_collection()
    unknown_collection = await get_unknown_users_collection()
    rank_collection = await get_rank_history_collection()
    sessions_collection = await get_admin_sessions_collection()
    
    # Count documents
    known_users = await known_collection.count_documents({})
    unknown_users = await unknown_collection.count_documents({})
    rank_changes = await rank_collection.count_documents({})
    active_sessions = await sessions_collection.count_documents({})
    
    # Calculate total messages from known users
    pipeline = [
        {"$group": {"_id": None, "total": {"$sum": "$TotalMsg"}}}
    ]
    result = await known_collection.aggregate(pipeline).to_list(1)
    total_messages = result[0]["total"] if result else 0
    
    # Count total distinct guilds seen in messages
    message_db = await get_message_db()
    message_collection = message_db["messages"]
    total_guilds = len(await message_collection.distinct("guild.id"))
    
    return StatisticsResponse(
        known_users=known_users,
        unknown_users=unknown_users,
        total_users=known_users + unknown_users,
        total_messages=total_messages,
        total_guilds=total_guilds,
        rank_changes=rank_changes,
        active_sessions=active_sessions
    )


@router.get("/statistics/top-users")
@limiter.limit("30/minute")
async def get_top_users(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    Get top users by message count.
    """
    collection = await get_known_users_collection()
    
    cursor = collection.find().sort("TotalMsg", -1).limit(limit)
    users = await cursor.to_list(length=limit)
    
    return [
        TopUser(
            roblox_username=user["RobloxUsername"],
            total_messages=user.get("TotalMsg", 0),
            guild_count=user.get("GuildCount", 0)
        )
        for user in users
    ]


@router.get("/statistics/rank-distribution")
@limiter.limit("30/minute")
async def get_rank_distribution(
    request: Request,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    Get distribution of ranks (from rank history).
    """
    collection = await get_rank_history_collection()
    
    # Get latest rank for each user
    pipeline = [
        {"$sort": {"RecordedAt": -1}},
        {"$group": {"_id": "$RobloxUsername", "latestRank": {"$first": "$NewRank"}}},
        {"$group": {"_id": "$latestRank", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    results = await collection.aggregate(pipeline).to_list(100)
    
    return [
        RankDistribution(rank=item["_id"] or "Unknown", count=item["count"])
        for item in results
        if item["_id"]
    ]


# ============================================================================
# User Management Endpoints
# ============================================================================

@router.get("/users", response_model=PaginatedResponse)
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    page: int = 1,
    limit: int = 50,
    sort: str = "TotalMsg",
    order: str = "desc",
    filters: UserFilterParams = Depends(get_user_filters),
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    List all known users with pagination and filtering.
    """
    collection = await get_known_users_collection()
    
    query = build_user_query(filters)
    pagination = get_pagination_params(page, limit, sort, order)
    
    return await paginate(collection, query, pagination)


@router.get("/users/unknown", response_model=PaginatedResponse)
@limiter.limit("30/minute")
async def list_unknown_users(
    request: Request,
    page: int = 1,
    limit: int = 50,
    sort: str = "TotalMsg",
    order: str = "desc",
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    List all unknown users with pagination.
    """
    collection = await get_unknown_users_collection()
    
    pagination = get_pagination_params(page, limit, sort, order)
    
    return await paginate(collection, {}, pagination)


# ============================================================================
# Audit Log Endpoints
# ============================================================================

@router.get("/audit-logs", response_model=PaginatedResponse)
@limiter.limit("30/minute")
async def get_audit_logs(
    request: Request,
    page: int = 1,
    limit: int = 50,
    event_type: str = None,
    action: str = None,
    actor: str = None,
    date_from: datetime = None,
    date_to: datetime = None,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    Get audit logs with filtering and pagination.
    """
    collection = await get_audit_logs_collection()
    
    # Build query
    query = {}
    
    if event_type:
        query["event_type"] = event_type
    
    if action:
        query["action"] = action
    
    if actor:
        query["actor"] = {"$regex": actor, "$options": "i"}
    
    if date_from:
        query["timestamp"] = query.get("timestamp", {})
        query["timestamp"]["$gte"] = date_from
    
    if date_to:
        query["timestamp"] = query.get("timestamp", {})
        query["timestamp"]["$lte"] = date_to
    
    pagination = get_pagination_params(page, limit, "timestamp", "desc")
    
    return await paginate(collection, query, pagination)


@router.get("/audit-logs/summary")
@limiter.limit("30/minute")
async def get_audit_summary(
    request: Request,
    days: int = Query(7, ge=1, le=90),
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """
    Get audit log summary for the past N days.
    """
    collection = await get_audit_logs_collection()
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Count by event type
    pipeline = [
        {"$match": {"timestamp": {"$gte": cutoff}}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    
    results = await collection.aggregate(pipeline).to_list(20)
    
    # Total count
    total = await collection.count_documents({"timestamp": {"$gte": cutoff}})
    
    return {
        "period_days": days,
        "total_events": total,
        "by_type": {item["_id"]: item["count"] for item in results}
    }
