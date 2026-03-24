"""
Authentication utilities for UserLooker.
Handles JWT token creation, validation, and user authentication.
"""

import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# JWT Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
if SECRET_KEY == "your-secret-key-change-in-production":
    print("[WARNING] Using default JWT_SECRET_KEY! Set a strong secret in .env for production.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# Admin Discord IDs (comma-separated in .env)
_admin_ids_raw = os.getenv("ADMIN_DISCORD_IDS", "")
ADMIN_DISCORD_IDS = [id.strip() for id in _admin_ids_raw.split(",") if id.strip()]

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


class TokenData(BaseModel):
    """Token payload model."""
    sub: str  # Discord user ID
    username: str
    role: str = "admin"
    exp: Optional[datetime] = None


class CurrentUser(BaseModel):
    """Current authenticated user model."""
    discord_id: str
    username: str
    role: str
    avatar: Optional[str] = None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.
    
    Args:
        data: Payload data (should include 'sub' for user ID)
        expires_delta: Optional custom expiration time
        
    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token with longer expiration.
    
    Args:
        data: Payload data
        
    Returns:
        Encoded JWT refresh token string
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[TokenData]:
    """
    Verify and decode a JWT token.
    
    Args:
        token: The JWT token string
        
    Returns:
        TokenData if valid, None if invalid
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        role: str = payload.get("role", "user")
        
        if user_id is None:
            return None
            
        return TokenData(sub=user_id, username=username, role=role)
    except JWTError:
        return None


def is_admin(discord_id: str) -> bool:
    """
    Check if a Discord user ID is in the admin whitelist.
    
    Args:
        discord_id: Discord user ID to check
        
    Returns:
        True if admin, False otherwise
    """
    return discord_id in ADMIN_DISCORD_IDS


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    """
    Dependency to get the current authenticated user.
    
    Raises:
        HTTPException: If token is invalid or missing
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if token is None:
        raise credentials_exception
    
    token_data = verify_token(token)
    
    if token_data is None:
        raise credentials_exception
    
    return CurrentUser(
        discord_id=token_data.sub,
        username=token_data.username,
        role=token_data.role
    )


async def get_current_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """
    Dependency to verify the current user is an admin.
    
    Raises:
        HTTPException: If user is not an admin
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return current_user


async def get_optional_user(token: str = Depends(oauth2_scheme)) -> Optional[CurrentUser]:
    """
    Dependency to optionally get the current user (for rate limiting tiers).
    Returns None if not authenticated instead of raising exception.
    """
    if token is None:
        return None
    
    token_data = verify_token(token)
    
    if token_data is None:
        return None
    
    return CurrentUser(
        discord_id=token_data.sub,
        username=token_data.username,
        role=token_data.role
    )
