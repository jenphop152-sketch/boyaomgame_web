"""
Rate limiting middleware for UserLooker API.
Uses slowapi for request rate limiting.
"""

import os
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# Redis URL for distributed rate limiting (optional)
REDIS_URL = os.getenv("REDIS_URL")

# Configure limiter with in-memory storage by default
# Redis is optional for distributed deployments
try:
    if REDIS_URL and REDIS_URL.strip():
        # Use Redis for distributed rate limiting
        limiter = Limiter(
            key_func=get_remote_address,
            storage_uri=REDIS_URL
        )
    else:
        # Use in-memory storage (for single instance)
        limiter = Limiter(
            key_func=get_remote_address,
            storage_uri="memory://"
        )
except Exception:
    # Fallback to in-memory if Redis connection fails
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri="memory://"
    )


def get_rate_limit_key(request: Request) -> str:
    """
    Get rate limit key based on user authentication status.
    
    Authenticated users get a separate rate limit pool.
    """
    # Check for Authorization header
    auth_header = request.headers.get("Authorization")
    
    if auth_header and auth_header.startswith("Bearer "):
        # For authenticated users, use their token as key
        # This gives each user their own rate limit pool
        token = auth_header.split(" ")[1][:20]  # Use first 20 chars of token
        return f"user:{token}"
    
    # For anonymous users, use IP address
    return get_remote_address(request)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Custom handler for rate limit exceeded.
    Returns a JSON response with rate limit info.
    """
    # Parse the rate limit string (e.g., "30 per 1 minute")
    limit_string = str(exc.detail)
    
    response = JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "message": f"Rate limit exceeded: {limit_string}",
            "detail": "Please slow down your requests",
            "retry_after": 60  # Default retry after 60 seconds
        },
        headers={
            "Retry-After": "60",
            "X-RateLimit-Limit": limit_string
        }
    )
    
    return response


# Rate limit decorators for different tiers
# Usage: @limiter.limit("30/minute")

# Anonymous tier: 30 requests per minute
ANONYMOUS_LIMIT = "30/minute"

# Authenticated tier: 100 requests per minute  
AUTHENTICATED_LIMIT = "100/minute"

# Admin tier: 500 requests per minute
ADMIN_LIMIT = "500/minute"


def setup_rate_limiting(app):
    """
    Set up rate limiting on a FastAPI application.
    
    Usage:
        from middleware.rate_limit import setup_rate_limiting, limiter
        
        app = FastAPI()
        setup_rate_limiting(app)
        
        @app.get("/endpoint")
        @limiter.limit("30/minute")
        async def endpoint(request: Request):
            ...
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
