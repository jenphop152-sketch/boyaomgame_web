from fastapi import FastAPI, HTTPException, Request, Query, Depends
from database import get_known_users_collection, get_unknown_users_collection, get_rank_history_collection, log_user_search
from utils.audit import log_search
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv
from utils.auth import get_current_user, CurrentUser

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="UserLooker API",
    description="Discord user data lookup and tracking API",
    version="2.0.0"
)

# CORS Middleware
from fastapi.middleware.cors import CORSMiddleware

# Get allowed origins from environment, defaulting to localhost for dev
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
ALLOWED_ORIGINS = [origin.strip() for origin in _cors_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting
from middleware.rate_limit import setup_rate_limiting, limiter

setup_rate_limiting(app)

# Audit Logging Middleware
from middleware.audit import AuditMiddleware

app.add_middleware(AuditMiddleware)

# Include Routers
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.notes import router as notes_router

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(notes_router)

# Message DB connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
message_db_client = AsyncIOMotorClient(MONGO_URI)
message_db = message_db_client["message_db"]

# ============================================================================
# Models
# ============================================================================

class DiscordAccount(BaseModel):
    DiscordUserId: str
    DiscordUsername: str


class KnownUser(BaseModel):
    RobloxUsername: str
    DiscordAccounts: List[DiscordAccount] = []
    FirstMsgFound: Optional[datetime] = None
    LastMsgFound: Optional[datetime] = None
    TotalMsg: Optional[int] = 0
    GuildCount: Optional[int] = 0

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class UnknownUser(BaseModel):
    DiscordUserId: str
    DiscordUsername: str
    Nickname: Optional[str] = None
    Reason: Optional[str] = None
    FirstMsgFound: Optional[datetime] = None
    LastMsgFound: Optional[datetime] = None
    TotalMsg: Optional[int] = 0
    GuildCount: Optional[int] = 0

    class Config:
        populate_by_name = True
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None
        }


class RankHistoryEntry(BaseModel):
    """Rank history entry model."""
    previous_rank: Optional[str] = None
    new_rank: str
    recorded_at: datetime


class ActivityDataPoint(BaseModel):
    """Activity data point for charts."""
    date: str
    count: int


class GuildActivity(BaseModel):
    """Guild activity breakdown."""
    guild_name: str
    message_count: int
    percentage: float


# ============================================================================
# Public Endpoints
# ============================================================================

@app.get("/")
@limiter.limit("60/minute")
async def root(request: Request):
    """Health check endpoint."""
    return {"message": "User Looker API is running", "version": "2.0.0"}


@app.get("/user/roblox/{roblox_username}", response_model=KnownUser)
@limiter.limit("30/minute")
async def get_user_by_roblox(
    request: Request, 
    roblox_username: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get user by Roblox username."""
    # Log search (internal session)
    await log_user_search(current_user.discord_id, roblox_username)
    # Audit log (system tracking)
    await log_search(
        actor=current_user.username,
        search_type="roblox",
        search_value=roblox_username,
        ip_address=request.client.host
    )
    
    collection = await get_known_users_collection()
    user_data = await collection.find_one({"RobloxUsername": roblox_username})

    if user_data:
        # Calculate real guild count if Discord account matches
        if "DiscordAccounts" in user_data and user_data["DiscordAccounts"]:
            discord_id = user_data["DiscordAccounts"][0]["DiscordUserId"]
            try:
                guild_ids = await message_db["messages"].distinct("guild.id", {"discord_user_id": discord_id})
                real_guild_count = len(guild_ids)
                if real_guild_count > 0:
                    user_data["GuildCount"] = real_guild_count
            except Exception as e:
                print(f"Error counting guilds for roblox user: {e}")

        # Ensure GuildCount defaults to 0 if not present and no real count found
        if "GuildCount" not in user_data or user_data["GuildCount"] is None:
            user_data["GuildCount"] = 0

        return user_data
    
    raise HTTPException(status_code=404, detail="User not found")


@app.get("/user/discord/{discord_id}")
@limiter.limit("30/minute")
async def get_user_by_discord(
    request: Request, 
    discord_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get user by Discord ID - searches both known and unknown users."""
    # Log search (internal session)
    await log_user_search(current_user.discord_id, discord_id)
    # Audit log (system tracking)
    await log_search(
        actor=current_user.username,
        search_type="discord",
        search_value=discord_id,
        ip_address=request.client.host
    )
    
    # Calculate real guild count and total messages from messages
    try:
        # Guilds
        guild_ids = await message_db["messages"].distinct("guild.id", {"discord_user_id": discord_id})
        real_guild_count = len(guild_ids)
        
        # Total Messages
        real_msg_count = await message_db["messages"].count_documents({"discord_user_id": discord_id})
    except Exception as e:
        print(f"Error counting stats: {e}")
        real_guild_count = 0
        real_msg_count = 0

    # First check known_users (Find ALL accounts)
    known_collection = await get_known_users_collection()
    cursor = known_collection.find({
        "DiscordAccounts.DiscordUserId": discord_id
    })
    known_users_list = await cursor.to_list(length=20)

    # Then check unknown_users
    unknown_collection = await get_unknown_users_collection()
    unknown_user = await unknown_collection.find_one({"DiscordUserId": discord_id})

    # Logic:
    # If we have known users, return them list.
    # If we have unknown user, return that.
    # We need a unified response structure for "Discord Search" that might differ slightly 
    # or we pack it into 'data'.
    
    # For backward compatibility with frontend, we'll return a main 'data' object
    # but add a 'linked_roblox_accounts' list.

    response_data = {}
    user_type = "unknown"

    if known_users_list:
        user_type = "known"
        # Use the first one as "main" for legacy display compatibility
        main_user = known_users_list[0]
        # Calculate dynamic stats if needed
        if real_guild_count > 0:
            main_user["GuildCount"] = real_guild_count
        if real_msg_count > 0:
            main_user["TotalMsg"] = real_msg_count
            
        response_data = KnownUser(**main_user).model_dump()
        
        # Add list of all roblox usernames found
        response_data["associated_roblox_users"] = [
            {"username": u["RobloxUsername"], "data": KnownUser(**u).model_dump()} 
            for u in known_users_list
        ]

    elif unknown_user:
        user_type = "unknown"
        if real_guild_count > 0:
            unknown_user["GuildCount"] = real_guild_count
        if real_msg_count > 0:
            unknown_user["TotalMsg"] = real_msg_count
        
        response_data = UnknownUser(**unknown_user).model_dump()
        response_data["associated_roblox_users"] = [] # None for unknown

    else:
        # Not found in either DB, but maybe messages exist?
        pass

    if response_data:
        return {"type": user_type, "data": response_data}
    
    raise HTTPException(status_code=404, detail="User not found")


@app.get("/user/discord/{discord_id}/messages")
@limiter.limit("30/minute")
async def get_user_messages(
    request: Request, 
    discord_id: str, 
    limit: int = 50, 
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get messages for a Discord user from message_db."""
    # Query the single messages collection
    messages_collection = message_db["messages"]
    
    messages = []
    # Find messages where discord_user_id matches
    cursor = messages_collection.find({"discord_user_id": discord_id}).sort("timestamp", -1).limit(limit)
    
    async for msg in cursor:
        msg["_id"] = str(msg["_id"])  # Convert ObjectId to string
        messages.append(msg)
    
    # Return empty array if no messages (not 404) - friendlier for frontend
    
    return {"discord_id": discord_id, "message_count": len(messages), "messages": messages}


# ============================================================================
# Rank History Endpoint
# ============================================================================

@app.get("/user/roblox/{roblox_username}/rank-history")
@limiter.limit("30/minute")
async def get_rank_history(
    request: Request, 
    roblox_username: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get rank history for a Roblox user.
    
    Returns the complete rank progression timeline.
    """
    collection = await get_rank_history_collection()
    
    # Find all rank changes for this user, sorted by date
    cursor = collection.find({"RobloxUsername": roblox_username}).sort("RecordedAt", -1)
    history = await cursor.to_list(length=100)
    
    if not history:
        raise HTTPException(status_code=404, detail="No rank history found for this user")
    
    entries = [
        RankHistoryEntry(
            previous_rank=entry.get("PreviousRank"),
            new_rank=entry.get("NewRank"),
            recorded_at=entry.get("RecordedAt")
        )
        for entry in history
    ]
    
    return {
        "roblox_username": roblox_username,
        "total_changes": len(entries),
        "current_rank": entries[0].new_rank if entries else None,
        "history": entries
    }


# ============================================================================
# Activity Stats Endpoint
# ============================================================================

@app.get("/user/discord/{discord_id}/activity")
@limiter.limit("30/minute")
async def get_user_activity(
    request: Request,
    discord_id: str,
    period: str = Query("30d", pattern="^(7d|30d|90d|1y|all)$"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get message activity over time for charting.
    
    Period options: 7d, 30d, 90d, 1y, all
    """
    # Query the single messages collection
    messages_collection = message_db["messages"]
    
    # Calculate date range
    now = datetime.now(timezone.utc)
    if period == "7d":
        start_date = now - timedelta(days=7)
    elif period == "30d":
        start_date = now - timedelta(days=30)
    elif period == "90d":
        start_date = now - timedelta(days=90)
    elif period == "1y":
        start_date = now - timedelta(days=365)
    else:
        start_date = None
    
    # Build query
    query = {"discord_user_id": discord_id}  # Base query for this user
    if start_date:
        query["timestamp"] = {"$gte": start_date.isoformat()}
    
    # Aggregate by date
    pipeline = [
        {"$match": query},
        {
            "$addFields": {
                "date": {"$substr": ["$timestamp", 0, 10]}  # Extract YYYY-MM-DD
            }
        },
        {
            "$group": {
                "_id": "$date",
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    results = await messages_collection.aggregate(pipeline).to_list(length=400)
    
    data = [
        ActivityDataPoint(date=item["_id"], count=item["count"])
        for item in results
        if item["_id"]
    ]
    
    total = sum(d.count for d in data)
    
    return {
        "discord_id": discord_id,
        "period": period,
        "total_messages": total,
        "data_points": len(data),
        "data": data
    }


@app.get("/user/discord/{discord_id}/analytics/heatmap")
@limiter.limit("30/minute")
async def get_activity_heatmap(
    request: Request,
    discord_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get activity heatmap data utilizing MongoDB native aggregations.
    """
    messages_collection = message_db["messages"]

    pipeline = [
        {"$match": {"discord_user_id": discord_id}},
        {
            "$addFields": {
                "dateObj": {
                    "$dateFromString": {
                        "dateString": "$timestamp",
                        "onError": None
                    }
                }
            }
        },
        {"$match": {"dateObj": {"$ne": None}}},
        {
            "$group": {
                "_id": {
                    "day": {"$dayOfWeek": "$dateObj"},
                    "hour": {"$hour": "$dateObj"}
                },
                "value": {"$sum": 1}
            }
        }
    ]
    
    cursor = messages_collection.aggregate(pipeline)
    
    result = []
    async for doc in cursor:
        mongo_day = doc["_id"]["day"]
        # Mongo 1=Sun, 2=Mon... React expects 0=Mon, 6=Sun
        day = 6 if mongo_day == 1 else mongo_day - 2
        hour = doc["_id"]["hour"]
        
        result.append({
            "day": day,
            "hour": hour,
            "value": doc["value"]
        })

    return {
        "discord_id": discord_id,
        "data": result
    }


# ============================================================================
# Guild Activity Endpoint
# ============================================================================

@app.get("/user/discord/{discord_id}/guilds")
@limiter.limit("30/minute")
async def get_user_guilds(
    request: Request, 
    discord_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get guild activity breakdown for a Discord user.
    
    Shows message distribution across guilds.
    """
    # Query the single messages collection
    messages_collection = message_db["messages"]
    
    # Aggregate by guild
    pipeline = [
        {"$match": {"discord_user_id": discord_id}},
        {
            "$group": {
                "_id": "$guild.name",
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"count": -1}}
    ]
    
    results = await messages_collection.aggregate(pipeline).to_list(length=50)
    
    if not results:
        raise HTTPException(status_code=404, detail="No guild data found for this user")
    
    total = sum(item["count"] for item in results)
    
    guilds = [
        GuildActivity(
            guild_name=item["_id"] or "Unknown Guild",
            message_count=item["count"],
            percentage=round((item["count"] / total) * 100, 1) if total > 0 else 0
        )
        for item in results
    ]
    
    return {
        "discord_id": discord_id,
        "total_guilds": len(guilds),
        "total_messages": total,
        "guilds": guilds
    }

