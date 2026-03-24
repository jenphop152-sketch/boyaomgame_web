"""
Search filter utilities for UserLooker API.
Provides query builders for user and message filtering.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class UserFilterParams(BaseModel):
    """Filter parameters for user searches."""
    rank: Optional[str] = Field(None, description="Filter by rank (partial match)")
    guild: Optional[str] = Field(None, description="Filter by guild name")
    min_messages: Optional[int] = Field(None, ge=0, description="Minimum message count")
    max_messages: Optional[int] = Field(None, ge=0, description="Maximum message count")
    date_from: Optional[datetime] = Field(None, description="Activity after this date")
    date_to: Optional[datetime] = Field(None, description="Activity before this date")
    has_multiple_accounts: Optional[bool] = Field(None, description="Has multiple Discord accounts")


class MessageFilterParams(BaseModel):
    """Filter parameters for message searches."""
    keyword: Optional[str] = Field(None, description="Search in message content")
    guild: Optional[str] = Field(None, description="Filter by guild name")
    date_from: Optional[datetime] = Field(None, description="Messages after this date")
    date_to: Optional[datetime] = Field(None, description="Messages before this date")
    has_attachments: Optional[bool] = Field(None, description="Has attachments")


def build_user_query(filters: UserFilterParams) -> dict:
    """
    Build a MongoDB query from user filter parameters.
    
    Args:
        filters: User filter parameters
        
    Returns:
        MongoDB query dictionary
    """
    query = {}
    
    if filters.rank:
        # Case-insensitive partial match on rank
        query["CurrentRank"] = {"$regex": filters.rank, "$options": "i"}
    
    if filters.min_messages is not None:
        query["TotalMsg"] = query.get("TotalMsg", {})
        query["TotalMsg"]["$gte"] = filters.min_messages
    
    if filters.max_messages is not None:
        query["TotalMsg"] = query.get("TotalMsg", {})
        query["TotalMsg"]["$lte"] = filters.max_messages
    
    if filters.date_from:
        query["LastMsgFound"] = query.get("LastMsgFound", {})
        query["LastMsgFound"]["$gte"] = filters.date_from
    
    if filters.date_to:
        query["LastMsgFound"] = query.get("LastMsgFound", {})
        query["LastMsgFound"]["$lte"] = filters.date_to
    
    if filters.has_multiple_accounts is True:
        query["$expr"] = {"$gt": [{"$size": "$DiscordAccounts"}, 1]}
    elif filters.has_multiple_accounts is False:
        query["$expr"] = {"$eq": [{"$size": "$DiscordAccounts"}, 1]}
    
    return query


def build_message_query(filters: MessageFilterParams) -> dict:
    """
    Build a MongoDB query from message filter parameters.
    
    Args:
        filters: Message filter parameters
        
    Returns:
        MongoDB query dictionary
    """
    query = {}
    
    if filters.keyword:
        # Case-insensitive text search
        query["content"] = {"$regex": filters.keyword, "$options": "i"}
    
    if filters.guild:
        query["guild.name"] = {"$regex": filters.guild, "$options": "i"}
    
    if filters.date_from:
        query["timestamp"] = query.get("timestamp", {})
        query["timestamp"]["$gte"] = filters.date_from.isoformat()
    
    if filters.date_to:
        query["timestamp"] = query.get("timestamp", {})
        query["timestamp"]["$lte"] = filters.date_to.isoformat()
    
    if filters.has_attachments is True:
        query["attachments"] = {"$exists": True, "$ne": []}
    elif filters.has_attachments is False:
        query["$or"] = [
            {"attachments": {"$exists": False}},
            {"attachments": []}
        ]
    
    return query


def get_user_filters(
    rank: str = None,
    guild: str = None,
    min_messages: int = None,
    max_messages: int = None,
    date_from: datetime = None,
    date_to: datetime = None,
    has_multiple_accounts: bool = None
) -> UserFilterParams:
    """
    FastAPI dependency for user filter parameters.
    
    Usage:
        @app.get("/users/search")
        async def search_users(filters: UserFilterParams = Depends(get_user_filters)):
            query = build_user_query(filters)
    """
    return UserFilterParams(
        rank=rank,
        guild=guild,
        min_messages=min_messages,
        max_messages=max_messages,
        date_from=date_from,
        date_to=date_to,
        has_multiple_accounts=has_multiple_accounts
    )


def get_message_filters(
    keyword: str = None,
    guild: str = None,
    date_from: datetime = None,
    date_to: datetime = None,
    has_attachments: bool = None
) -> MessageFilterParams:
    """
    FastAPI dependency for message filter parameters.
    """
    return MessageFilterParams(
        keyword=keyword,
        guild=guild,
        date_from=date_from,
        date_to=date_to,
        has_attachments=has_attachments
    )
