"""
Admin Notes Routes.
Manage custom notes/tags for users (e.g. "Admin", "VIP").
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from typing import List
from pydantic import BaseModel
from datetime import datetime

from database import get_additional_data_collection
from utils.auth import get_current_admin, CurrentUser
from utils.audit import log_audit, EVENT_MODIFY

router = APIRouter(prefix="/admin/notes", tags=["Admin Notes"])

# Models
class AdminNote(BaseModel):
    note_name: str
    note_description: str
    note_emoji: str = "🛡️"  # Default emoji
    users: List[str] = []  # List of Roblox Usernames

class CreateNoteRequest(BaseModel):
    note_name: str
    note_description: str
    note_emoji: str = "🛡️"

class UpdateNoteUsersRequest(BaseModel):
    username: str
    action: str  # "add" or "remove"


@router.get("/", response_model=List[AdminNote])
async def get_all_notes(current_admin: CurrentUser = Depends(get_current_admin)):
    """Get all admin notes."""
    collection = await get_additional_data_collection()
    cursor = collection.find({})
    notes = await cursor.to_list(length=100)
    return [AdminNote(**note) for note in notes]


@router.post("/")
async def create_note(
    note: CreateNoteRequest,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """Create a new note type."""
    collection = await get_additional_data_collection()
    
    # Check if exists
    existing = await collection.find_one({"note_name": note.note_name})
    if existing:
        raise HTTPException(status_code=400, detail="Note with this name already exists")
    
    new_note = {
        "note_name": note.note_name,
        "note_description": note.note_description,
        "note_emoji": note.note_emoji,
        "users": [],
        "created_at": datetime.utcnow(),
        "created_by": current_admin.username
    }
    
    await collection.insert_one(new_note)
    
    await log_audit(
        event_type=EVENT_MODIFY,
        action="create_note",
        actor=current_admin.username,
        target=note.note_name,
        success=True
    )
    
    return {"message": "Note created successfully", "note": new_note}


@router.put("/{note_name}/users")
async def update_note_users(
    note_name: str,
    update: UpdateNoteUsersRequest,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """Add or remove a user from a note."""
    collection = await get_additional_data_collection()
    
    note = await collection.find_one({"note_name": note_name})
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    if update.action == "add":
        if update.username not in note.get("users", []):
            await collection.update_one(
                {"note_name": note_name},
                {"$push": {"users": update.username}}
            )
    elif update.action == "remove":
        await collection.update_one(
            {"note_name": note_name},
            {"$pull": {"users": update.username}}
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    
    await log_audit(
        event_type=EVENT_MODIFY,
        action=f"update_note_users_{update.action}",
        actor=current_admin.username,
        target=f"{note_name}:{update.username}",
        success=True
    )
    
    return {"message": f"User {update.action}ed successfully"}


@router.delete("/{note_name}")
async def delete_note(
    note_name: str,
    current_admin: CurrentUser = Depends(get_current_admin)
):
    """Delete a note type."""
    collection = await get_additional_data_collection()
    
    result = await collection.delete_one({"note_name": note_name})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note not found")
        
    await log_audit(
        event_type=EVENT_MODIFY,
        action="delete_note",
        actor=current_admin.username,
        target=note_name,
        success=True
    )
    
    return {"message": "Note deleted"}


# Public/User endpoint to fetch notes for a specific user
@router.get("/user/{username}", response_model=List[AdminNote])
async def get_user_notes(username: str):
    """Get all notes applicable to a specific user."""
    collection = await get_additional_data_collection()
    
    # Find all notes where 'users' array contains this username
    cursor = collection.find({"users": username})
    notes = await cursor.to_list(length=50)
    
    return [AdminNote(**note) for note in notes]
