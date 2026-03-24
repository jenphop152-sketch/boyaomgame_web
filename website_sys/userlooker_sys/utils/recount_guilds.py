import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MON_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

async def recount_guilds():
    print("Starting Guild Count Recrunch...")
    client = AsyncIOMotorClient(MON_URI)
    db = client["message_db"]
    msg_col = db["messages"]
    
    # User DBs
    known_col = db["known_users"]
    unknown_col = db["unknown_users"]

    # 1. Get all distinct user IDs from messages
    print("Fetching distinct users from messages...")
    user_ids = await msg_col.distinct("discord_user_id")
    print(f"Found {len(user_ids)} users with messages.")

    updated_count = 0
    
    for uid in user_ids:
        # 2. Count distinct guilds for this user
        guild_ids = await msg_col.distinct("guild.id", {"discord_user_id": uid})
        real_count = len(guild_ids)
        
        if real_count > 0:
            # 3. Update Known Users
            res = await known_col.update_one(
                {"DiscordAccounts.DiscordUserId": uid},
                {"$set": {"GuildCount": real_count}}
            )
            
            if res.matched_count == 0:
                # 4. Update Unknown Users if not known
                await unknown_col.update_one(
                    {"DiscordUserId": uid},
                    {"$set": {"GuildCount": real_count}}
                )
            
            updated_count += 1
            if updated_count % 10 == 0:
                print(f"Processed {updated_count} users...", end='\r')

    print(f"\nRecount Complete. Updated {updated_count} users.")

if __name__ == "__main__":
    asyncio.run(recount_guilds())
