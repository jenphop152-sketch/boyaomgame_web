"""Test script to verify MongoDB data after extraction."""
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "discord_data")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

print("=== Known Users Collection ===")
for user in db["known_users"].find():
    print(f"\nRoblox: {user['RobloxUsername']}")
    print(f"  Discord Accounts: {user['DiscordAccounts']}")
    print(f"  First Msg: {user.get('FirstMsgFound')}")
    print(f"  Last Msg: {user.get('LastMsgFound')}")
    print(f"  Total Msgs: {user.get('TotalMsg')}")
    print(f"  Guild Count: {user.get('GuildCount')}")

print("\n\n=== Unknown Users Collection ===")
unknown_count = db["unknown_users"].count_documents({})
print(f"Total unknown users: {unknown_count}")
for user in db["unknown_users"].find().limit(5):
    print(f"\nDiscord ID: {user['DiscordUserId']}")
    print(f"  Username: {user['DiscordUsername']}")
    print(f"  Nickname: {user.get('Nickname')}")
    print(f"  Reason: {user.get('Reason')}")
