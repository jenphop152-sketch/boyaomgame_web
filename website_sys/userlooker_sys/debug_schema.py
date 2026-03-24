import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def inspect_schema():
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    client = AsyncIOMotorClient(mongo_uri)
    db = client["message_db"]
    collection = db["messages"]

    # Get one document
    doc = await collection.find_one({})
    if doc and 'guild' in doc:
        g = doc['guild']
        if isinstance(g, dict):
             print(f"Guild Keys: {list(g.keys())}")
             # Check distinct result test
             distinct_ids = await collection.distinct("guild.id")
             print(f"Total distinct guild IDs found overall: {len(distinct_ids)}")
        else:
             print("Guild field is not a dict")

if __name__ == "__main__":
    asyncio.run(inspect_schema())
