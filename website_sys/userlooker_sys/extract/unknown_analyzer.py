"""
Unknown User AI Analyzer
Analyzes messages from unknown users using Gemini AI to detect Roblox usernames and ranks.

Usage:
    python extract/unknown_analyzer.py [--port PORT] [--dry-run]
    
Examples:
    python extract/unknown_analyzer.py
    python extract/unknown_analyzer.py --port 27018
    python extract/unknown_analyzer.py --dry-run  # Preview without making changes
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# Configuration
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
DB_NAME = os.getenv("DB_NAME", "discord_data")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# AI Configuration
CONFIDENCE_THRESHOLD = 60  # Minimum confidence to classify as known
RATE_LIMIT_DELAY = 5  # Seconds between API calls
MAX_MESSAGES_PER_USER = 500  # Limit messages to stay under token cap

# Global MongoDB references
client = None
db = None
unknown_users_collection = None
known_users_collection = None
confirmed_unknown_collection = None
message_db = None


def init_mongodb(port: int = None):
    """Initialize MongoDB connection."""
    global client, db, unknown_users_collection, known_users_collection, confirmed_unknown_collection, message_db
    
    mongo_port = port if port else MONGO_PORT
    mongo_uri = f"mongodb://{MONGO_HOST}:{mongo_port}"
    
    print(f"Connecting to MongoDB at {mongo_uri}...")
    client = MongoClient(mongo_uri)
    db = client[DB_NAME]
    unknown_users_collection = db["unknown_users"]
    known_users_collection = db["known_users"]
    confirmed_unknown_collection = db["confirmed_unknown"]
    message_db = client["message_db"]


def load_valid_ranks() -> list:
    """Load valid ranks from rank.txt file."""
    ranks = []
    rank_file = Path(__file__).parent.parent / "RankHistory" / "rank.txt"
    
    if not rank_file.exists():
        print(f"Warning: rank.txt not found at {rank_file}")
        return ranks
    
    with open(rank_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('--'):
                continue
            
            if '|' in line:
                rank_part = line.split('|')[0].strip()
                
                if ' or ' in line:
                    parts = line.split(' or ')
                    for part in parts:
                        if '|' in part:
                            alt_rank = part.split('|')[0].strip()
                            if alt_rank and alt_rank not in ranks:
                                ranks.append(alt_rank)
                elif rank_part and rank_part not in ranks:
                    ranks.append(rank_part)
    
    return ranks


# Load valid ranks at startup
VALID_RANKS = load_valid_ranks()


def init_gemini():
    """Initialize Gemini AI client."""
    import google.generativeai as genai
    
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY must be set in environment/.env")
    
    genai.configure(api_key=GEMINI_API_KEY)
    return genai.GenerativeModel("gemini-2.0-flash-lite")


def get_user_messages(discord_id: str) -> list:
    """Fetch messages from message_db for a Discord user."""
    user_collection = message_db[discord_id]
    messages = list(user_collection.find().sort("timestamp", -1).limit(MAX_MESSAGES_PER_USER))
    return messages


def format_messages_for_ai(messages: list, discord_id: str) -> str:
    """Format messages into text for AI analysis."""
    formatted_lines = []
    
    for msg in messages:
        timestamp = msg.get("timestamp", "")
        content = msg.get("content", "")
        
        # Skip empty messages
        if not content or not content.strip():
            continue
        
        # Truncate very long messages
        if len(content) > 500:
            content = content[:500] + "..."
        
        formatted_lines.append(f"[{timestamp}] {content}")
    
    return "\n".join(formatted_lines)


def create_ai_prompt(discord_id: str, formatted_messages: str) -> str:
    """Create the prompt for Gemini AI."""
    valid_ranks_list = "\n".join([f"- {rank}" for rank in VALID_RANKS])
    
    return f"""You are analyzing Discord messages to identify a Roblox user's username and military rank.

The user might mention their Roblox username or receive messages mentioning their rank.

**VALID RANKS (you MUST use one of these exact formats if detecting a rank):**
{valid_ranks_list}

Analyze these messages from Discord user ID {discord_id}:

{formatted_messages}

Based on the messages, determine:
1. The user's Roblox username (if detectable)
2. Their military rank (if detectable) - MUST be exactly one from the valid ranks list above
3. Your confidence level (0-100)

Respond ONLY with valid JSON in this exact format:
{{"user_id": "{discord_id}", "username": "detected_username_or_null", "rank": "detected_rank_or_null", "classified": "known_or_unknown", "confident": confidence_number_or_null}}

Rules:
- If you can detect both username AND rank with reasonable confidence, set classified to "known"
- If you cannot detect username or rank, set classified to "unknown", username to null, rank to null, confident to null
- Only set classified to "known" if you're reasonably sure about the detection
- The username should be a valid Roblox username (3-20 alphanumeric characters or underscores)
- The rank MUST be exactly one of the valid ranks listed above, not a variation"""


def analyze_with_gemini(model, discord_id: str, messages: list) -> dict:
    """Send messages to Gemini AI for analysis."""
    formatted_messages = format_messages_for_ai(messages, discord_id)
    
    if not formatted_messages.strip():
        return {
            "user_id": discord_id,
            "username": None,
            "rank": None,
            "classified": "unknown",
            "confident": None
        }
    
    prompt = create_ai_prompt(discord_id, formatted_messages)
    
    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()
        
        # Extract JSON from response
        if response_text.startswith("```"):
            # Remove markdown code blocks
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1])
        
        result = json.loads(response_text)
        return result
    except json.JSONDecodeError as e:
        print(f"    Failed to parse AI response: {e}")
        return None
    except Exception as e:
        print(f"    AI error: {e}")
        return None


def move_to_known_users(unknown_user: dict, ai_result: dict):
    """Move user from unknown_users to known_users."""
    discord_id = unknown_user["DiscordUserId"]
    discord_username = unknown_user.get("DiscordUsername", "")
    
    # Create known user document (matching standard format with Note field)
    confidence = ai_result.get("confident", 0)
    known_doc = {
        "RobloxUsername": ai_result["username"],
        "DiscordAccounts": [{
            "DiscordUserId": discord_id,
            "DiscordUsername": discord_username
        }],
        "FirstMsgFound": unknown_user.get("FirstMsgFound"),
        "LastMsgFound": unknown_user.get("LastMsgFound"),
        "TotalMsg": unknown_user.get("TotalMsg", 0),
        "GuildCount": unknown_user.get("GuildCount", 0),
        "Note": f"AI Analyzed ({confidence}% confidence)"
    }
    
    # Check if this Roblox username already exists
    existing = known_users_collection.find_one({"RobloxUsername": ai_result["username"]})
    
    if existing:
        # Add Discord account to existing user
        known_users_collection.update_one(
            {"RobloxUsername": ai_result["username"]},
            {
                "$addToSet": {
                    "DiscordAccounts": {
                        "DiscordUserId": discord_id,
                        "DiscordUsername": discord_username
                    }
                },
                "$inc": {"TotalMsg": unknown_user.get("TotalMsg", 0)}
            }
        )
    else:
        # Insert new known user
        known_users_collection.insert_one(known_doc)
    
    # Delete from unknown_users
    unknown_users_collection.delete_one({"DiscordUserId": discord_id})


def move_to_confirmed_unknown(unknown_user: dict):
    """Move user from unknown_users to confirmed_unknown."""
    discord_id = unknown_user["DiscordUserId"]
    
    # Add analysis timestamp
    unknown_user["AnalyzedAt"] = datetime.utcnow()
    unknown_user["_id"] = None  # Remove old _id
    del unknown_user["_id"]
    
    # Insert to confirmed_unknown
    confirmed_unknown_collection.insert_one(unknown_user)
    
    # Delete from unknown_users
    unknown_users_collection.delete_one({"DiscordUserId": discord_id})


def main():
    parser = argparse.ArgumentParser(
        description="Analyze unknown users with Gemini AI to detect usernames and ranks"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="MongoDB port (default: 27017 or MONGO_PORT env var)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview analysis without making database changes"
    )
    
    args = parser.parse_args()
    
    # Initialize connections
    init_mongodb(port=args.port)
    model = init_gemini()
    
    # Get all unknown users
    unknown_users = list(unknown_users_collection.find())
    
    if not unknown_users:
        print("No unknown users to analyze.")
        return
    
    print(f"Found {len(unknown_users)} unknown user(s) to analyze")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}%")
    print(f"Rate limit delay: {RATE_LIMIT_DELAY}s")
    if args.dry_run:
        print("DRY RUN MODE - No changes will be made")
    print()
    
    # Counters
    moved_to_known = 0
    moved_to_confirmed_unknown = 0
    errors = 0
    
    for i, user in enumerate(unknown_users):
        discord_id = user["DiscordUserId"]
        discord_username = user.get("DiscordUsername", "Unknown")
        
        print(f"[{i+1}/{len(unknown_users)}] Analyzing: {discord_username} ({discord_id})")
        
        # Get user messages
        messages = get_user_messages(discord_id)
        
        if not messages:
            print(f"    No messages found, moving to confirmed_unknown")
            if not args.dry_run:
                move_to_confirmed_unknown(user)
            moved_to_confirmed_unknown += 1
            continue
        
        print(f"    Found {len(messages)} message(s)")
        
        # Analyze with AI
        result = analyze_with_gemini(model, discord_id, messages)
        
        if result is None:
            print(f"    AI analysis failed, skipping")
            errors += 1
            time.sleep(RATE_LIMIT_DELAY)
            continue
        
        classified = result.get("classified", "unknown")
        confidence = result.get("confident")
        username = result.get("username")
        rank = result.get("rank")
        
        print(f"    AI Result: classified={classified}, confidence={confidence}, username={username}, rank={rank}")
        
        # Decide action based on result
        if classified == "known" and confidence and confidence >= CONFIDENCE_THRESHOLD and username:
            print(f"    -> Moving to known_users (confidence {confidence}% >= {CONFIDENCE_THRESHOLD}%)")
            if not args.dry_run:
                move_to_known_users(user, result)
            moved_to_known += 1
        else:
            print(f"    -> Moving to confirmed_unknown")
            if not args.dry_run:
                move_to_confirmed_unknown(user)
            moved_to_confirmed_unknown += 1
        
        # Rate limiting
        if i < len(unknown_users) - 1:
            print(f"    Waiting {RATE_LIMIT_DELAY}s before next request...")
            time.sleep(RATE_LIMIT_DELAY)
    
    # Summary
    print()
    print("=== Summary ===")
    print(f"Total analyzed: {len(unknown_users)}")
    print(f"Moved to known_users: {moved_to_known}")
    print(f"Moved to confirmed_unknown: {moved_to_confirmed_unknown}")
    print(f"Errors: {errors}")
    if args.dry_run:
        print("(DRY RUN - no actual changes made)")


if __name__ == "__main__":
    main()
