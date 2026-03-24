"""
Audit logging utilities for UserLooker API.
Tracks admin actions and significant events.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel
from database import get_audit_logs_collection


class AuditLogEntry(BaseModel):
    """Audit log entry model."""
    timestamp: datetime
    event_type: str  # auth, access, modify, system
    action: str
    actor: str
    target: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


# Event type constants
EVENT_AUTH = "auth"
EVENT_ACCESS = "access"
EVENT_MODIFY = "modify"
EVENT_SYSTEM = "system"

# Action constants
ACTION_LOGIN = "login"
ACTION_LOGOUT = "logout"
ACTION_SEARCH = "user_search"
ACTION_VIEW = "view_details"
ACTION_EXTRACT = "data_extraction"
ACTION_ERROR = "error"


async def log_audit(
    event_type: str,
    action: str,
    actor: str,
    target: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None
) -> str:
    """
    Log an audit event to the database.
    
    Args:
        event_type: Type of event (auth, access, modify, system)
        action: Specific action performed
        actor: User or IP who performed the action
        target: Resource that was affected
        details: Additional context
        ip_address: Client IP address
        user_agent: Client user agent string
        success: Whether the action succeeded
        error_message: Error message if failed
        
    Returns:
        The inserted document ID as string
    """
    collection = await get_audit_logs_collection()
    
    log_entry = {
        "timestamp": datetime.utcnow(),
        "event_type": event_type,
        "action": action,
        "actor": actor,
        "target": target,
        "details": details,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "success": success,
        "error_message": error_message
    }
    
    result = await collection.insert_one(log_entry)
    return str(result.inserted_id)


async def log_login(
    discord_id: str,
    username: str,
    ip_address: str = None,
    success: bool = True,
    error: str = None
):
    """Log a login attempt."""
    await log_audit(
        event_type=EVENT_AUTH,
        action=ACTION_LOGIN,
        actor=f"{username} ({discord_id})",
        details={"discord_id": discord_id, "username": username},
        ip_address=ip_address,
        success=success,
        error_message=error
    )


async def log_logout(discord_id: str, username: str, ip_address: str = None):
    """Log a logout."""
    await log_audit(
        event_type=EVENT_AUTH,
        action=ACTION_LOGOUT,
        actor=f"{username} ({discord_id})",
        ip_address=ip_address
    )


async def log_search(
    actor: str,
    search_type: str,
    search_value: str,
    ip_address: str = None,
    found: bool = True
):
    """Log a user search."""
    await log_audit(
        event_type=EVENT_ACCESS,
        action=ACTION_SEARCH,
        actor=actor,
        target=search_value,
        details={"search_type": search_type, "found": found},
        ip_address=ip_address,
        success=found
    )


async def log_error(
    action: str,
    error_message: str,
    actor: str = "system",
    details: Dict = None
):
    """Log a system error."""
    await log_audit(
        event_type=EVENT_SYSTEM,
        action=ACTION_ERROR,
        actor=actor,
        error_message=error_message,
        details=details,
        success=False
    )


def get_client_info(request) -> tuple:
    """
    Extract client IP and user agent from request.
    
    Returns:
        Tuple of (ip_address, user_agent)
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent
