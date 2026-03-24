"""
Pagination utilities for UserLooker API.
Provides consistent pagination across all list endpoints.
"""

from typing import Any, List, Optional, TypeVar
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorCollection

T = TypeVar('T')


class PaginationParams(BaseModel):
    """Query parameters for pagination."""
    page: int = Field(1, ge=1, description="Page number (1-indexed)")
    limit: int = Field(50, ge=1, le=100, description="Items per page (max 100)")
    sort: str = Field("_id", description="Field to sort by")
    order: str = Field("desc", pattern="^(asc|desc)$", description="Sort order")


class PaginationMeta(BaseModel):
    """Pagination metadata included in response."""
    page: int
    limit: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class PaginatedResponse(BaseModel):
    """Standard paginated response format."""
    data: List[Any]
    pagination: PaginationMeta


def get_pagination_params(
    page: int = 1,
    limit: int = 50,
    sort: str = "_id",
    order: str = "desc"
) -> PaginationParams:
    """
    FastAPI dependency for pagination parameters.
    
    Usage:
        @app.get("/items")
        async def get_items(pagination: PaginationParams = Depends(get_pagination_params)):
            ...
    """
    # Clamp values
    page = max(1, page)
    limit = max(1, min(100, limit))
    order = order.lower() if order.lower() in ["asc", "desc"] else "desc"
    
    return PaginationParams(page=page, limit=limit, sort=sort, order=order)


async def paginate(
    collection: AsyncIOMotorCollection,
    query: dict,
    params: PaginationParams,
    projection: Optional[dict] = None
) -> PaginatedResponse:
    """
    Paginate a MongoDB query.
    
    Args:
        collection: MongoDB collection
        query: MongoDB query filter
        params: Pagination parameters
        projection: Optional field projection
        
    Returns:
        PaginatedResponse with data and pagination metadata
    """
    # Calculate skip
    skip = (params.page - 1) * params.limit
    
    # Get total count
    total = await collection.count_documents(query)
    
    # Calculate total pages
    total_pages = (total + params.limit - 1) // params.limit if total > 0 else 0
    
    # Determine sort direction
    sort_direction = -1 if params.order == "desc" else 1
    
    # Execute query
    cursor = collection.find(query, projection)
    cursor = cursor.sort(params.sort, sort_direction)
    cursor = cursor.skip(skip).limit(params.limit)
    
    # Fetch results
    data = await cursor.to_list(length=params.limit)
    
    # Convert ObjectIds to strings for JSON serialization
    for item in data:
        if "_id" in item:
            item["_id"] = str(item["_id"])
    
    # Build pagination metadata
    pagination = PaginationMeta(
        page=params.page,
        limit=params.limit,
        total=total,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1
    )
    
    return PaginatedResponse(data=data, pagination=pagination)


def paginate_list(
    items: List[Any],
    params: PaginationParams
) -> PaginatedResponse:
    """
    Paginate an in-memory list.
    
    Args:
        items: List of items to paginate
        params: Pagination parameters
        
    Returns:
        PaginatedResponse with data and pagination metadata
    """
    total = len(items)
    total_pages = (total + params.limit - 1) // params.limit if total > 0 else 0
    
    # Calculate slice
    start = (params.page - 1) * params.limit
    end = start + params.limit
    
    # Slice data
    data = items[start:end]
    
    pagination = PaginationMeta(
        page=params.page,
        limit=params.limit,
        total=total,
        total_pages=total_pages,
        has_next=params.page < total_pages,
        has_prev=params.page > 1
    )
    
    return PaginatedResponse(data=data, pagination=pagination)
