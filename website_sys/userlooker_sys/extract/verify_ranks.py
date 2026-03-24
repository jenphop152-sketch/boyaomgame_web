"""Verify rank history in MongoDB."""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "discord_data")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

print("=== Rank History Collection ===")
for user in db["rank_history"].find():
    print(f"\nRoblox: {user['RobloxUsername']}")
    print(f"  Current Rank: {user.get('CurrentRank')}")
    print(f"  Rank History:")
    for entry in user.get('RankHistory', []):
        print(f"    - {entry.get('PreviousRank')} -> {entry.get('NewRank')} at {entry.get('RecordedAt')}")
