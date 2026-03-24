"""
Discord OAuth2 authentication routes for UserLooker.
Handles Discord login flow and session management.
"""

import os
from datetime import datetime
from typing import Optional, List
import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from utils.auth import (
    create_access_token,
    create_refresh_token,
    verify_token,
    get_current_user,
    is_admin,
    CurrentUser,
    ADMIN_DISCORD_IDS
)
from database import get_user_sessions_collection
from utils.audit import log_login, log_logout

load_dotenv()

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Discord OAuth2 Configuration
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8001/auth/discord/callback")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Security Check
if not os.getenv("SECRET_KEY"):
    print("[WARNING] SECRET_KEY is not set in .env! Using a fallback for development only.")

if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
    print("[WARNING] Discord Client ID/Secret not set in .env! Authentication will fail.")

# Discord API URLs
DISCORD_AUTH_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Refresh token request model."""
    refresh_token: str


class UserResponse(BaseModel):
    """User info response model."""
    discord_id: str
    username: str
    avatar: Optional[str] = None
    role: str
    recent_searches: List[str] = []


@router.get("/discord")
async def discord_login():
    """
    Redirect to Discord OAuth2 authorization page.
    """
    if not DISCORD_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="Discord OAuth is not configured. Set DISCORD_CLIENT_ID in .env"
        )
    
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify"
    }
    
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{DISCORD_AUTH_URL}?{query_string}"
    
    return RedirectResponse(url=auth_url)


@router.get("/discord/callback")
async def discord_callback(code: str = None, error: str = None):
    """
    Handle Discord OAuth2 callback.
    Allows ALL users to login. Checks whitelist for Admin role.
    """
    if error:
        return RedirectResponse(url=f"{FRONTEND_URL}/login?error={error}")
    
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code not provided")
    
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Discord OAuth is not configured"
        )
    
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        print(f"[DEBUG] Exchanging code for tokens. URI: {DISCORD_REDIRECT_URI}")
        token_response = await client.post(
            DISCORD_TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if token_response.status_code != 200:
            print(f"[ERROR] Token exchange failed: {token_response.text}")
            try:
                error_detail = token_response.json().get("error_description", "Token exchange failed")
                error_body = token_response.json()
                print(f"[ERROR] Full response: {error_body}")
            except:
                error_detail = f"Token exchange failed (Status: {token_response.status_code})"
                
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error={error_detail}")
        
        tokens = token_response.json()
        discord_access_token = tokens["access_token"]
        
        # Get user info from Discord
        user_response = await client.get(
            DISCORD_USER_URL,
            headers={"Authorization": f"Bearer {discord_access_token}"}
        )
        
        if user_response.status_code != 200:
            return RedirectResponse(url=f"{FRONTEND_URL}/login?error=Failed to get user info")
        
        discord_user = user_response.json()
    
    discord_id = discord_user["id"]
    username = discord_user["username"]
    avatar = discord_user.get("avatar")
    
    # Determine Role
    user_role = "admin" if is_admin(discord_id) else "user"
    
    # Create JWT tokens
    jwt_access_token = create_access_token(data={
        "sub": discord_id,
        "username": username,
        "role": user_role
    })
    
    jwt_refresh_token = create_refresh_token(data={
        "sub": discord_id,
        "username": username
    })
    
    # Store session in MongoDB (generic user_sessions)
    await store_session(
        discord_id=discord_id,
        username=username,
        avatar=avatar,
        discord_tokens=tokens,
        role=user_role
    )
    
    # Log login
    await log_login(discord_id, username, success=True)
    
    # Redirect to frontend with token
    return RedirectResponse(
        url=f"{FRONTEND_URL}/auth/callback?token={jwt_access_token}&refresh={jwt_refresh_token}"
    )


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest):
    """
    Get a new access token using a refresh token.
    """
    token_data = verify_token(request.refresh_token)
    
    if token_data is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )
    
    # Check if user is still admin (revocation check)
    current_role = "admin" if is_admin(token_data.sub) else "user"
    
    # Create new access token
    new_access_token = create_access_token(data={
        "sub": token_data.sub,
        "username": token_data.username,
        "role": current_role
    })
    
    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
async def logout(current_user: CurrentUser = Depends(get_current_user)):
    """
    Log out the current user.
    """
    collection = await get_user_sessions_collection()
    await collection.delete_one({"discord_id": current_user.discord_id})
    
    await log_logout(current_user.discord_id, current_user.username)
    
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    """
    Get the current authenticated user's info.
    """
    # Fetch additional info from session
    collection = await get_user_sessions_collection()
    session = await collection.find_one({"discord_id": current_user.discord_id})
    
    avatar = session.get("avatar") if session else None
    recent_searches = session.get("recent_searches", []) if session else []
    
    return UserResponse(
        discord_id=current_user.discord_id,
        username=current_user.username,
        avatar=avatar,
        role=current_user.role,
        recent_searches=recent_searches
    )


async def store_session(
    discord_id: str,
    username: str, 
    avatar: Optional[str],
    discord_tokens: dict,
    role: str
):
    """
    Store or update a user session in MongoDB.
    """
    collection = await get_user_sessions_collection()
    
    # Check if session exists to preserve things like recent_searches
    existing_session = await collection.find_one({"discord_id": discord_id})
    
    session_update = {
        "discord_id": discord_id,
        "username": username,
        "avatar": avatar,
        "discord_access_token": discord_tokens.get("access_token"),
        "discord_refresh_token": discord_tokens.get("refresh_token"),
        "role": role,
        "last_activity": datetime.utcnow()
    }
    
    if not existing_session:
        session_update["created_at"] = datetime.utcnow()
        session_update["recent_searches"] = []
    
    await collection.update_one(
        {"discord_id": discord_id},
        {"$set": session_update},
        upsert=True
    )
