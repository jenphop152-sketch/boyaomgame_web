from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "discord_data") # Default database name, can be changed

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
message_db = client["message_db"]

async def get_message_db():
    return message_db

async def get_user_collection():
    return db["users"] # Assuming collection name is 'users'

async def get_known_users_collection():
    return db["known_users"]

async def get_unknown_users_collection():
    return db["unknown_users"]

async def get_rank_history_collection():
    return db["rank_history"]

async def get_confirmed_unknown_collection():
    return db["confirmed_unknown"]

async def get_admin_sessions_collection():
    """Get the admin sessions collection for OAuth session storage."""
    return db["admin_sessions"]

async def get_user_sessions_collection():
    """Get the user sessions collection for all users."""
    return db["user_sessions"]

async def get_audit_logs_collection():
    """Get the audit logs collection for tracking admin actions."""
    return db["audit_logs"]

async def get_additional_data_collection():
    """Get the additional data collection for admin notes."""
    return db["additional_data"]

async def log_user_search(discord_id: str, query: str):
    """
    Log a search query to the user's recent searches.
    Maintains a list of unique recent searches (max 10).
    """
    collection = await get_user_sessions_collection()
    
    # Use $pull to remove if exists (to move to top), then $push to front with $slice
    # MongoDB 4.4 compatible approach:
    # 1. Pull query if exists
    await collection.update_one(
        {"discord_id": discord_id},
        {"$pull": {"recent_searches": query}}
    )
    
    # 2. Push to front and slice to 10
    await collection.update_one(
        {"discord_id": discord_id},
        {"$push": {
            "recent_searches": {
                "$each": [query],
                "$position": 0,
                "$slice": 10
            }
        }}
    )
