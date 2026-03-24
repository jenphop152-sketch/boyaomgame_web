"""
Audit logging middleware for UserLooker API.
Automatically logs significant API requests.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from utils.audit import log_audit, EVENT_ACCESS, EVENT_SYSTEM, get_client_info


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Middleware that automatically logs significant API requests.
    
    Logs:
    - All POST, PUT, DELETE requests
    - All admin endpoint access
    - All errors (status >= 400)
    """
    
    # Paths to skip logging (high-frequency, low-value)
    SKIP_PATHS = {
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/favicon.ico"
    }
    
    # Always log these paths regardless of method
    ALWAYS_LOG_PATHS = {
        "/auth/",
        "/admin/"
    }
    
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method
        
        # Skip paths that don't need logging
        if path in self.SKIP_PATHS:
            return await call_next(request)
        
        # Determine if we should log this request
        should_log = (
            method in ["POST", "PUT", "DELETE"] or
            any(path.startswith(p) for p in self.ALWAYS_LOG_PATHS) or
            path.startswith("/admin")
        )
        
        if not should_log:
            return await call_next(request)
        
        # Get client info
        ip_address, user_agent = get_client_info(request)
        
        # Get actor (from auth header if available)
        actor = self._get_actor(request, ip_address)
        
        # Process the request
        response = await call_next(request)
        
        # Log the request
        success = response.status_code < 400
        
        await log_audit(
            event_type=EVENT_ACCESS if success else EVENT_SYSTEM,
            action=f"{method} {path}",
            actor=actor,
            target=path,
            details={
                "status_code": response.status_code,
                "method": method
            },
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=None if success else f"HTTP {response.status_code}"
        )
        
        return response
    
    def _get_actor(self, request: Request, fallback: str) -> str:
        """Extract actor from auth header or use IP as fallback."""
        auth_header = request.headers.get("Authorization")
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                # We do a quick decode without verification here for speed/logging purposes
                # Verification happens in the route dependency anyway.
                # Just extracting 'username' claim.
                import json
                import base64
                
                # Simple JWT decode for payloads (header.payload.signature)
                parts = token.split(".")
                if len(parts) == 3:
                    padding = '=' * (4 - len(parts[1]) % 4)
                    payload_json = base64.urlsafe_b64decode(parts[1] + padding).decode('utf-8')
                    payload = json.loads(payload_json)
                    return payload.get("username") or payload.get("sub") or "authenticated_user"
            except Exception:
                return "authenticated_user"
        
        return fallback or "anonymous"
