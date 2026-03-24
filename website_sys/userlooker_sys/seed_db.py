import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
import os

async def seed():
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client["discord_data"]
    collection = db["users"]

    # Clear existing data for this user to avoid duplicates if re-run
    await collection.delete_many({"UserId": "1383083682511716482"})

    data = {
        "UserId": "1383083682511716482",
        "FirstMsgFound": datetime.fromisoformat("2025-09-17T13:31:20.314"),
        "LastMsgFound": datetime.fromisoformat("2025-10-13T08:22:01.161"),
        "TotalMsg": 37
    }

    result = await collection.insert_one(data)
    print(f"Inserted document with ID: {result.inserted_id}")

if __name__ == "__main__":
    asyncio.run(seed())
