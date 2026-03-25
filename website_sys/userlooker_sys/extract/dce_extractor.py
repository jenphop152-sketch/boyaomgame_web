"""
DiscordChatExporter Data Extraction Script
Extracts user data from DCE JSON exports and stores in MongoDB.

Usage:
    python extract/dce_extractor.py <json_file_or_directory>
    python extract/dce_extractor.py --b2 <bucket-name> <prefix>
    
Examples:
    python extract/dce_extractor.py extract/example.json
    python extract/dce_extractor.py extract/  # Process all JSON files in directory
    python extract/dce_extractor.py --b2 my-bucket exports/2024/  # From B2 bucket
"""

import ijson
import re
import os
import sys
import time
import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

load_dotenv()

# Rate limiting configuration - adjust these to prevent MongoDB overload
BATCH_SIZE = int(os.getenv("MONGO_BATCH_SIZE", "100"))  # Documents per batch
BATCH_DELAY = float(os.getenv("MONGO_BATCH_DELAY", "0.5"))  # Seconds between batches
MESSAGE_BATCH_SIZE = int(os.getenv("MONGO_MSG_BATCH_SIZE", "50"))  # Messages per batch
MESSAGE_BATCH_DELAY = float(os.getenv("MONGO_MSG_BATCH_DELAY", "0.3"))  # Delay for message batches

# MongoDB configuration (connection is lazy-loaded)
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
DB_NAME = os.getenv("DB_NAME", "discord_data")
MESSAGE_DB_NAME = os.getenv("MESSAGE_DB_NAME", "message_db")

# Global MongoDB references (initialized in init_mongodb)
client = None
db = None
known_users_collection = None
unknown_users_collection = None
rank_history_collection = None
message_db = None


def init_mongodb(port: int = None):
    """Initialize MongoDB connection with optional custom port."""
    global client, db, known_users_collection, unknown_users_collection, rank_history_collection, message_db
    
    mongo_port = port if port else MONGO_PORT
    mongo_uri = f"mongodb://{MONGO_HOST}:{mongo_port}"
    
    print(f"Connecting to MongoDB at {mongo_uri}...")
    
    try:
        # Create client with short timeout for connection check
        client = MongoClient(
            mongo_uri, 
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        
        # Verify connection by listing databases (doesn't require admin)
        client.list_database_names()
        print("MongoDB connection successful!")
        
    except Exception as e:
        print(f"Failed to connect to MongoDB: {e}")
        print(f"\nPlease ensure MongoDB is running at {mongo_uri}")
        print("Tips:")
        print("  - Check if MongoDB service is running")
        print("  - Verify the host and port are correct")
        print("  - Use --port flag to specify a different port")
        print("  - Check SSH tunnel if connecting remotely")
        sys.exit(1)
    
    db = client[DB_NAME]
    known_users_collection = db["known_users"]
    unknown_users_collection = db["unknown_users"]
    rank_history_collection = db["rank_history"]
    
    # Message DB setup
    message_db_client = client
    message_db = message_db_client[MESSAGE_DB_NAME]
    
    # Ensure indexes for the single messages collection
    try:
        print("Ensuring indexes on message_db.messages...")
        # Compound index for fast user history lookup: sort by user, then time
        message_db["messages"].create_index([("discord_user_id", 1), ("timestamp", -1)])
        # Unique index on message ID to prevent duplicates
        message_db["messages"].create_index("id", unique=True)
        print("Indexes verified")
    except Exception as e:
        print(f"Warning: Could not create indexes: {e}")
    
    print(f"Using database: {DB_NAME}")


# Backblaze B2 configuration (S3-compatible)
B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APP_KEY = os.getenv("B2_APP_KEY")
B2_ENDPOINT = os.getenv("B2_ENDPOINT", "https://s3.us-west-000.backblazeb2.com")


def get_b2_client():
    """Get boto3 S3 client configured for Backblaze B2."""
    import boto3
    
    if not B2_KEY_ID or not B2_APP_KEY:
        raise ValueError("B2_KEY_ID and B2_APP_KEY must be set in environment/.env")
    
    return boto3.client(
        's3',
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY
    )


def list_b2_json_files(bucket: str, prefix: str = "") -> list:
    """List all JSON files in a B2 bucket with given prefix."""
    s3 = get_b2_client()
    files = []
    
    print(f"  Scanning B2 bucket (this may take a while)...")
    paginator = s3.get_paginator('list_objects_v2')
    page_count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        page_count += 1
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.json'):
                files.append(obj['Key'])
        print(f"  ... scanned {page_count} page(s), found {len(files)} JSON file(s) so far", end='\r', flush=True)
    
    print()  # newline after progress
    return files


def download_b2_file(bucket: str, key: str) -> Path:
    """Download a file from B2 to a temporary file with progress. Returns temp file path."""
    s3 = get_b2_client()
    
    # Get file size first
    try:
        head = s3.head_object(Bucket=bucket, Key=key)
        total_size = head['ContentLength']
        total_mb = total_size / (1024 * 1024)
    except Exception:
        total_size = 0
        total_mb = 0
    
    # Create temp file with .json extension
    temp_fd, temp_path = tempfile.mkstemp(suffix='.json')
    os.close(temp_fd)
    
    if total_size > 0:
        downloaded = [0]  # use list for closure mutability
        
        def progress_callback(bytes_transferred):
            downloaded[0] += bytes_transferred
            done_mb = downloaded[0] / (1024 * 1024)
            pct = (downloaded[0] / total_size) * 100
            print(f"    Downloading: {done_mb:.1f} MB / {total_mb:.1f} MB ({pct:.0f}%)", end='\r', flush=True)
        
        s3.download_file(bucket, key, temp_path, Callback=progress_callback)
        print()  # newline after progress
    else:
        s3.download_file(bucket, key, temp_path)
    
    return Path(temp_path)


def extract_roblox_username(nickname: Optional[str]) -> tuple[Optional[str], str]:
    """
    Extract Roblox username from Discord nickname.
    
    Patterns supported:
    - "OF-9, GEN, ACIC | Username" → "Username"
    - "DEP | OF-1a, 2LT | Username" → "Username"
    - "OF-1a, 2LT 123 | Username" → "Username"
    - "OF-1a, 2LT, COM | Username" → "Username"
    
    Returns:
        (username, reason) - username is None if extraction failed
        reason can be: "known", "no_nickname", "no_separator", "invalid_format"
    """
    if not nickname:
        return None, "no_nickname"
    
    # Split by | and get the last part
    parts = nickname.split("|")
    if len(parts) < 2:
        return None, "no_separator"
    
    potential_username = parts[-1].strip()
    
    # Validate: Roblox usernames are 3-20 chars, alphanumeric + underscore
    if re.match(r'^[a-zA-Z0-9_]{3,20}$', potential_username):
        return potential_username, "known"
    
    return None, "invalid_format"


def load_valid_ranks() -> list:
    """
    Load valid ranks from rank.txt file.
    Returns list of ranks sorted by length (longest first) for proper matching.
    """
    ranks = []
    rank_file = Path(__file__).parent.parent / "RankHistory" / "rank.txt"
    
    if not rank_file.exists():
        print(f"Warning: rank.txt not found at {rank_file}")
        return ranks
    
    with open(rank_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('--'):
                continue
            
            # Extract rank part (before | Username)
            if '|' in line:
                rank_part = line.split('|')[0].strip()
                
                # Handle "or" alternatives like "OF-6, COLS | Username or OF-6, SRCOL | Username"
                if ' or ' in line:
                    parts = line.split(' or ')
                    for part in parts:
                        if '|' in part:
                            alt_rank = part.split('|')[0].strip()
                            if alt_rank and alt_rank not in ranks:
                                ranks.append(alt_rank)
                elif rank_part and rank_part not in ranks:
                    ranks.append(rank_part)
    
    # Sort by length (longest first) so "OF-9, GEN, ACIC" matches before "OF-9, GEN"
    ranks.sort(key=len, reverse=True)
    return ranks


# Load valid ranks at module startup
VALID_RANKS = load_valid_ranks()


def extract_rank(nickname: Optional[str]) -> Optional[str]:
    """
    Extract rank from Discord nickname by matching against valid ranks from rank.txt.
    
    Examples:
    - "OF-9, GEN, ACIC | Username" → "OF-9, GEN, ACIC" (valid rank)
    - "OF-1a, 2LT, ACOS | Username" → "OF-1a, 2LT" (ACOS ignored, not in list)
    - "OF-1a, 2LT 123 | Username" → "OF-1a, 2LT" (123 ignored)
    
    Returns:
        valid rank string or None if not found
    """
    if not nickname:
        return None
    
    parts = nickname.split("|")
    if len(parts) < 2:
        return None
    
    # Get the part before the last | (which contains the rank)
    rank_part = parts[-2].strip()
    
    # Try to match against valid ranks (longest first)
    for valid_rank in VALID_RANKS:
        if rank_part.startswith(valid_rank):
            # Make sure it's a complete match (followed by space, comma, or end)
            if len(rank_part) == len(valid_rank):
                return valid_rank
            next_char = rank_part[len(valid_rank)]
            if next_char in ' ,':
                return valid_rank
    
    return None


def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse ISO timestamp string to datetime object."""
    # Remove timezone info for parsing
    if '+' in timestamp_str:
        timestamp_str = timestamp_str.split('+')[0]
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1]
    
    # Handle different precision levels for microseconds
    if '.' in timestamp_str:
        base, frac = timestamp_str.rsplit('.', 1)
        # Pad to 6 digits for microseconds
        frac = frac.ljust(6, '0')[:6]
        timestamp_str = f"{base}.{frac}"
    
    return datetime.fromisoformat(timestamp_str)


def process_json_file(filepath: Path) -> dict:
    """
    Process a single DCE JSON file and extract user data.
    
    Returns:
        dict with 'known' and 'unknown' user lists
    """
    # Extract guild and channel info first
    guild_info = {"id": None, "name": "Unknown Guild", "iconUrl": None}
    channel_info = {"id": None, "name": "Unknown Channel", "type": None, "category": None}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # parsing 'guild' object directly
            for guild_data in ijson.items(f, 'guild'):
                guild_info = {
                    "id": guild_data.get('id'),
                    "name": guild_data.get('name', 'Unknown Guild'),
                    "iconUrl": guild_data.get('iconUrl')
                }
                break
    except Exception as e:
        print(f"Warning: Could not extract guild info: {e}")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # parsing 'channel' object directly
            for channel_data in ijson.items(f, 'channel'):
                channel_info = {
                    "id": channel_data.get('id'),
                    "name": channel_data.get('name', 'Unknown Channel'),
                    "type": channel_data.get('type'),
                    "category": channel_data.get('category')
                }
                break
    except Exception as e:
        print(f"Warning: Could not extract channel info: {e}")
    
    guild_name = guild_info["name"]

    # Aggregate data per user
    # Key: (RobloxUsername) for known, (DiscordUserId) for tracking
    known_users = {}  # roblox_username -> user_data
    unknown_users = {}  # discord_id -> user_data
    all_messages = [] # List of message objects buffer
    user_ranks = {}  # roblox_username -> {rank, timestamp}
    
    messages_saved_in_file = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        # Stream messages
        messages = ijson.items(f, 'messages.item')
        
        for msg in messages:
            author = msg.get('author', {})
            if author.get('isBot', False):
                continue  # Skip bots
            
            discord_id = author.get('id')
            discord_username = author.get('name')
            nickname = author.get('nickname')
            timestamp = msg.get('timestamp')
            
            if not discord_id or not timestamp:
                continue
            
            # Add guild, channel, and USER info to the message
            msg["guild"] = guild_info
            msg["channel"] = channel_info
            msg["discord_user_id"] = discord_id  # IMPORTANT: Link message to user
            all_messages.append(msg)
            
            # Immediately save and clear buffer to prevent memory bloat
            if len(all_messages) >= MESSAGE_BATCH_SIZE:
                messages_saved_in_file += save_messages_to_db(all_messages)
                all_messages.clear()
            
            parsed_time = parse_timestamp(timestamp)
            roblox_username, reason = extract_roblox_username(nickname)
            
            # Extract rank for rank history
            rank = extract_rank(nickname)
            
            if roblox_username:
                # Known user - group by Roblox username
                if roblox_username not in known_users:
                    known_users[roblox_username] = {
                        "RobloxUsername": roblox_username,
                        "DiscordAccounts": [],  # List of {DiscordUserId, DiscordUsername}
                        "FirstMsgFound": parsed_time,
                        "LastMsgFound": parsed_time,
                        "TotalMsg": 0,
                        "GuildCount": 0,
                        "_guilds_seen": set(),
                        "_discord_ids_seen": set()
                    }
                
                user_data = known_users[roblox_username]
                
                # Add Discord account if not already tracked
                if discord_id not in user_data["_discord_ids_seen"]:
                    user_data["_discord_ids_seen"].add(discord_id)
                    user_data["DiscordAccounts"].append({
                        "DiscordUserId": discord_id,
                        "DiscordUsername": discord_username
                    })
                
                # Update timestamps
                if parsed_time < user_data["FirstMsgFound"]:
                    user_data["FirstMsgFound"] = parsed_time
                if parsed_time > user_data["LastMsgFound"]:
                    user_data["LastMsgFound"] = parsed_time
                
                user_data["TotalMsg"] += 1
                user_data["_guilds_seen"].add(guild_name)
                user_data["GuildCount"] = len(user_data["_guilds_seen"])
                
                # Track rank for this user (keep latest by timestamp)
                if rank and roblox_username:
                    if roblox_username not in user_ranks:
                        user_ranks[roblox_username] = {"rank": rank, "timestamp": parsed_time}
                    elif parsed_time > user_ranks[roblox_username]["timestamp"]:
                        user_ranks[roblox_username] = {"rank": rank, "timestamp": parsed_time}
            else:
                # Unknown user - group by Discord ID
                if discord_id not in unknown_users:
                    unknown_users[discord_id] = {
                        "DiscordUserId": discord_id,
                        "DiscordUsername": discord_username,
                        "Nickname": nickname,
                        "Reason": reason,
                        "FirstMsgFound": parsed_time,
                        "LastMsgFound": parsed_time,
                        "TotalMsg": 0,
                        "GuildCount": 0,
                        "_guilds_seen": set()
                    }
                
                user_data = unknown_users[discord_id]
                
                # Update timestamps
                if parsed_time < user_data["FirstMsgFound"]:
                    user_data["FirstMsgFound"] = parsed_time
                if parsed_time > user_data["LastMsgFound"]:
                    user_data["LastMsgFound"] = parsed_time
                
                user_data["TotalMsg"] += 1
                user_data["_guilds_seen"].add(guild_name)
                user_data["GuildCount"] = len(user_data["_guilds_seen"])
    
    # Clean up internal tracking sets
    for user in known_users.values():
        del user["_guilds_seen"]
        del user["_discord_ids_seen"]
    
    for user in unknown_users.values():
        del user["_guilds_seen"]
    
    # Flush remaining messages
    if all_messages:
        messages_saved_in_file += save_messages_to_db(all_messages)
        all_messages.clear()
        
    return {
        "known": list(known_users.values()),
        "unknown": list(unknown_users.values()),
        "messages_saved": messages_saved_in_file,
        "ranks": user_ranks,
        "guild_name": guild_name,
        "guild_info": guild_info,
        "channel_info": channel_info
    }


def save_to_mongodb(known: list, unknown: list):
    """
    Save extracted users to MongoDB.
    Uses bulk upsert operations with rate limiting to prevent overload.
    """
    known_count = 0
    unknown_count = 0
    
    # Build bulk operations for known users
    known_operations = []
    for user in known:
        known_operations.append(UpdateOne(
            {"RobloxUsername": user["RobloxUsername"]},
            {
                "$set": {
                    "RobloxUsername": user["RobloxUsername"],
                    "LastMsgFound": user["LastMsgFound"],
                    "GuildCount": user["GuildCount"]
                },
                "$addToSet": {
                    "DiscordAccounts": {"$each": user["DiscordAccounts"]}
                },
                "$min": {"FirstMsgFound": user["FirstMsgFound"]},
                "$inc": {"TotalMsg": user["TotalMsg"]}
            },
            upsert=True
        ))
    
    # Execute known users in batches with delay
    for i in range(0, len(known_operations), BATCH_SIZE):
        batch = known_operations[i:i + BATCH_SIZE]
        if batch:
            result = known_users_collection.bulk_write(batch, ordered=False)
            known_count += result.upserted_count + result.modified_count
            if i + BATCH_SIZE < len(known_operations):
                time.sleep(BATCH_DELAY)  # Rate limiting delay
    
    # Build bulk operations for unknown users
    unknown_operations = []
    for user in unknown:
        unknown_operations.append(UpdateOne(
            {"DiscordUserId": user["DiscordUserId"]},
            {
                "$set": {
                    "DiscordUserId": user["DiscordUserId"],
                    "DiscordUsername": user["DiscordUsername"],
                    "Nickname": user["Nickname"],
                    "Reason": user["Reason"],
                    "LastMsgFound": user["LastMsgFound"],
                    "GuildCount": user["GuildCount"]
                },
                "$min": {"FirstMsgFound": user["FirstMsgFound"]},
                "$inc": {"TotalMsg": user["TotalMsg"]}
            },
            upsert=True
        ))
    
    # Execute unknown users in batches with delay
    for i in range(0, len(unknown_operations), BATCH_SIZE):
        batch = unknown_operations[i:i + BATCH_SIZE]
        if batch:
            result = unknown_users_collection.bulk_write(batch, ordered=False)
            unknown_count += result.upserted_count + result.modified_count
            if i + BATCH_SIZE < len(unknown_operations):
                time.sleep(BATCH_DELAY)  # Rate limiting delay
    
    return known_count, unknown_count


def cleanup_unknown_users():
    """
    Remove users from unknown_users collection if their Discord ID
    is found in any known_users DiscordAccounts.
    
    This handles the case where a user had no nickname in one server
    but had a nickname in another server.
    """
    # Get all Discord IDs from known_users
    known_discord_ids = set()
    for user in known_users_collection.find({}, {"DiscordAccounts": 1}):
        for account in user.get("DiscordAccounts", []):
            known_discord_ids.add(account.get("DiscordUserId"))
    
    if not known_discord_ids:
        return 0
    
    # Delete unknown users whose Discord ID is in known_users
    result = unknown_users_collection.delete_many({
        "DiscordUserId": {"$in": list(known_discord_ids)}
    })
    
    return result.deleted_count


def save_rank_history(user_ranks: dict):
    """
    Save rank history to MongoDB.
    Creates a NEW document for each rank change.
    Uses batched operations with rate limiting.
    
    Schema (one document per rank change):
    {
        "RobloxUsername": "BouncyBari",
        "PreviousRank": "OF-1a, 2LT",
        "NewRank": "OF-9, GEN, ACIC",
        "RecordedAt": datetime
    }
    """
    updates_count = 0
    documents_to_insert = []
    
    # Batch-fetch all latest ranks in one aggregation instead of per-user find_one
    usernames = [u for u, d in user_ranks.items() if d.get("rank")]
    latest_ranks = {}  # username -> latest NewRank
    
    if usernames:
        pipeline = [
            {"$match": {"RobloxUsername": {"$in": usernames}}},
            {"$sort": {"RecordedAt": -1}},
            {"$group": {
                "_id": "$RobloxUsername",
                "NewRank": {"$first": "$NewRank"}
            }}
        ]
        for doc in rank_history_collection.aggregate(pipeline):
            latest_ranks[doc["_id"]] = doc["NewRank"]
    
    for roblox_username, rank_data in user_ranks.items():
        current_rank = rank_data.get("rank")
        timestamp = rank_data.get("timestamp")
        
        if not current_rank:
            continue
        
        previous_rank = latest_ranks.get(roblox_username)
        
        # Only record if rank changed (or first time)
        if previous_rank != current_rank:
            documents_to_insert.append({
                "RobloxUsername": roblox_username,
                "PreviousRank": previous_rank,
                "NewRank": current_rank,
                "RecordedAt": timestamp
            })
    
    # Insert all new rank records in batches
    for i in range(0, len(documents_to_insert), BATCH_SIZE):
        batch = documents_to_insert[i:i + BATCH_SIZE]
        if batch:
            rank_history_collection.insert_many(batch)
            updates_count += len(batch)
            if i + BATCH_SIZE < len(documents_to_insert):
                time.sleep(BATCH_DELAY)  # Rate limiting delay
    
    return updates_count


def save_messages_to_db(messages: list):
    """
    Save messages to the SINGLE 'messages' collection.
    
    Uses bulk operations with rate limiting.
    """
    messages_saved = 0
    
    # Get the single collection
    messages_collection = message_db["messages"]
    
    # Build bulk operations
    operations = []
    for msg in messages:
        msg_id = msg.get("id")
        if msg_id:
            operations.append(UpdateOne(
                {"id": msg_id},
                {"$set": msg},
                upsert=True
            ))
    
    # Execute in batches with delay
    for i in range(0, len(operations), MESSAGE_BATCH_SIZE):
        batch = operations[i:i + MESSAGE_BATCH_SIZE]
        if batch:
            try:
                result = messages_collection.bulk_write(batch, ordered=False)
                messages_saved += result.upserted_count + result.modified_count
            except Exception as e:
                print(f"    ! Bulk write error (partial): {e}")
            
            if i + MESSAGE_BATCH_SIZE < len(operations):
                time.sleep(MESSAGE_BATCH_DELAY)
    
    return messages_saved


def process_files(files: list, source_type: str = "local", bucket: str = None):
    """
    Process files and save each to MongoDB immediately.
    
    This approach:
    - Reduces memory usage (don't accumulate all data)
    - Provides crash recovery (processed files are saved)
    - Spreads MongoDB load evenly over time
    
    Returns:
        dict with processing statistics
    """
    stats = {
        "files_processed": 0,
        "files_failed": 0,
        "total_known": 0,
        "total_unknown": 0,
        "total_messages": 0,
        "rank_updates": 0,
        "new_known": 0,
        "new_unknown": 0
    }
    
    total_files = len(files)
    
    for idx, filepath in enumerate(files, 1):
        if source_type == "b2":
            print(f"\n[{idx}/{total_files}] Downloading: {filepath}")
            temp_path = download_b2_file(bucket, filepath)
            display_name = Path(filepath).name
        else:
            temp_path = filepath
            display_name = filepath.name
        
        print(f"[{idx}/{total_files}] Processing: {display_name}")
        
        try:
            # Process the JSON file
            result = process_json_file(temp_path)
            
            # Safe print for guild name
            try:
                print(f"    Guild: {result['guild_name']}")
            except UnicodeEncodeError:
                print(f"    Guild: {result['guild_name'].encode('ascii', 'replace').decode()}")
            
            try:
                print(f"    Channel: {result['channel_info']['name']}")
            except UnicodeEncodeError:
                print(f"    Channel: {result['channel_info']['name'].encode('ascii', 'replace').decode()}")
            print(f"    Known users: {len(result['known'])}")
            print(f"    Unknown users: {len(result['unknown'])}")
            print(f"    Messages saved: {result['messages_saved']}")
            print(f"    Ranks: {len(result['ranks'])}")
            
            # SAVE IMMEDIATELY after each file
            print(f"    Saving to MongoDB...")
            
            # Save users
            new_known, new_unknown = save_to_mongodb(result["known"], result["unknown"])
            stats["new_known"] += new_known
            stats["new_unknown"] += new_unknown
            
            # Extract messages saved stat
            msgs_saved = result["messages_saved"]
            stats["total_messages"] += msgs_saved
            
            # Save rank history
            rank_updates = save_rank_history(result["ranks"])
            stats["rank_updates"] += rank_updates
            
            # Update stats
            stats["files_processed"] += 1
            stats["total_known"] += len(result["known"])
            stats["total_unknown"] += len(result["unknown"])
            
            print(f"    Saved: {new_known} new known, {new_unknown} new unknown, {msgs_saved} messages")
            
        except Exception as e:
            print(f"    Error: {e}")
            stats["files_failed"] += 1
            
        finally:
            # Clean up temp file if from B2
            if source_type == "b2" and temp_path.exists():
                os.unlink(temp_path)
    
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Extract user data from DiscordChatExporter JSON files"
    )
    parser.add_argument(
        "--b2", 
        nargs=2, 
        metavar=("BUCKET", "PREFIX"),
        help="Extract from Backblaze B2 bucket (e.g., --b2 my-bucket exports/)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="MongoDB port (default: 27017 or MONGO_PORT env var)"
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Local file or directory path"
    )
    
    args = parser.parse_args()
    
    # Initialize MongoDB connection
    init_mongodb(port=args.port)
    
    # Determine source
    if args.b2:
        bucket, prefix = args.b2
        print(f"Listing files from B2 bucket: {bucket}/{prefix}")
        files = list_b2_json_files(bucket, prefix)
        source_type = "b2"
        
        if not files:
            print(f"No JSON files found in bucket {bucket} with prefix {prefix}")
            sys.exit(1)
        
        print(f"Found {len(files)} JSON file(s) in B2 bucket")
        stats = process_files(files, source_type="b2", bucket=bucket)
    elif args.path:
        target = Path(args.path)
        
        if target.is_file():
            files = [target]
        elif target.is_dir():
            print(f"Scanning directory: {target}")
            print("(This may take a while for large directories or mounted storage...)")
            files = list(target.glob("**/*.json"))
            print(f"Found {len(files)} JSON file(s)")
        else:
            print(f"Error: {target} is not a valid file or directory")
            sys.exit(1)
        
        if not files:
            print(f"No JSON files found in {target}")
            sys.exit(1)
        
        print(f"\nProcessing {len(files)} JSON file(s)...")
        stats = process_files(files)
    else:
        parser.print_help()
        sys.exit(1)
    
    # Cleanup: Remove unknown users who were found as known in other servers
    print(f"\nCleaning up duplicate entries...")
    cleaned_count = cleanup_unknown_users()
    
    # Run Guild Recount (sync from message_db for accuracy)
    try:
        # Import dynamically to avoid circular issues or just add path if needed
        # Assuming utils is in python path
        sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
        from utils.recount_guilds import recount_guilds
        
        print(f"\nRunning final guild count synchronization...")
        import asyncio
        asyncio.run(recount_guilds())
    except Exception as e:
        print(f"[Warning] Failed to run guild recount: {e}")

    # Print summary
    print(f"\n{'='*50}")
    print(f"               EXTRACTION COMPLETE")
    print(f"{'='*50}")
    print(f"Files processed:      {stats['files_processed']}")
    if stats['files_failed'] > 0:
        print(f"Files failed:         {stats['files_failed']}")
    print(f"Total known users:    {stats['total_known']}")
    print(f"Total unknown users:  {stats['total_unknown']}")
    print(f"Global Message sync:  {stats['total_messages']} msgs saved")
    print(f"New Rank updates:     {stats['rank_updates']}")
    if stats['new_known'] > 0 or stats['new_unknown'] > 0:
        print(f"New profiles created: {stats['new_known']} known, {stats['new_unknown']} unknown")
    
    end_time = datetime.now()
    duration = end_time - start_time
    print(f"\nTotal time: {duration}")
    print("Done!")


if __name__ == "__main__":
    main()
