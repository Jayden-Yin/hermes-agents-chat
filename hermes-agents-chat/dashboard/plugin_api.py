"""
Hermes Chat — Dashboard Plugin API (FastAPI APIRouter).

Mounted by the Dashboard framework at /api/plugins/hermes-chat/.

Reuses the same Database → RoomService → AgentRouter stack as main.py,
exposed as a mountable FastAPI router with lazy initialization.
"""

from __future__ import annotations

import logging
import json
import os
import sys
import time
import yaml
from pathlib import Path
from typing import Optional

# Ensure the plugin's own directory is on sys.path so relative imports
# (agent_manager, database, models, room_service) resolve correctly when
# the Dashboard server imports this module via importlib.
_plugin_dir = Path(__file__).resolve().parent
if str(_plugin_dir) not in sys.path:
    sys.path.insert(0, str(_plugin_dir))

# Also ensure the hermes-agent source is on sys.path for run_agent imports
_hermes_agent_dir = Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"
if _hermes_agent_dir.exists() and str(_hermes_agent_dir) not in sys.path:
    sys.path.insert(0, str(_hermes_agent_dir))

# Ensure hermes-agent venv site-packages are available
_venv_sp = _hermes_agent_dir / "venv" / "Lib" / "site-packages"
if _venv_sp.exists() and str(_venv_sp) not in sys.path:
    sys.path.insert(0, str(_venv_sp))

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent_manager import registry
from database import Database
from models import (
    AgentCreate,
    AgentMemoryUpdate,
    AgentProfile,
    ContextClearResponse,
    FanOutResult,
    HealthResponse,
    MessageListResponse,
    MessageResponse,
    MessageSend,
    RoomCreate,
    RoomListResponse,
    RoomResponse,
    RoomUpdate,
    SummaryListResponse,
    SummaryResponse,
)
from room_service import RoomService

logger = logging.getLogger("hermes-chat.plugin")

# ─── Configuration ───────────────────────────────────────────────────────────

DB_PATH = os.environ.get(
    "HERMES_CHAT_DB",
    str(Path.home() / "AppData" / "Local" / "hermes" / "chat" / "hermes-chat.db"),
)

# User profile stored in plugin data directory
USER_DATA_DIR = Path.home() / "AppData" / "Local" / "hermes" / "chat"
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
USER_FILE = USER_DATA_DIR / "user.json"

# ─── Plugin State ────────────────────────────────────────────────────────────

_plugin_start_time: float = 0.0
_plugin_db: Database | None = None
_plugin_service: RoomService | None = None

# ─── Router ──────────────────────────────────────────────────────────────────

router = APIRouter(tags=["hermes-chat"])


# ─── Lifecycle Hooks ─────────────────────────────────────────────────────────

def init_plugin(db_path: str | None = None) -> None:
    """Initialize the plugin backend. Called by the Dashboard on startup."""
    global _plugin_start_time, _plugin_db, _plugin_service
    _plugin_start_time = time.time()
    path = db_path or DB_PATH
    _plugin_db = Database(path)
    # aiosqlite connect happens lazily on first request via ensure_initialized()


def ensure_initialized():
    """Lazily ensure DB is connected. Call at the top of every endpoint."""
    if _plugin_db is None:
        raise RuntimeError("hermes-chat plugin not initialized — call init_plugin()")
    return _plugin_db, _plugin_service


async def _connect_if_needed():
    """Connect DB + create service on first call."""
    global _plugin_service
    if _plugin_service is not None:
        return _plugin_db, _plugin_service
    if _plugin_db._conn is None:  # not yet connected
        await _plugin_db.connect()
    _plugin_service = RoomService(_plugin_db)
    return _plugin_db, _plugin_service


# ─── Health ──────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    db, svc = await _connect_if_needed()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_sec=time.time() - _plugin_start_time,
        room_count=await db.count_rooms(),
        agent_count=len(registry.names()),
        active_connections=0,
    )


# ─── Rooms ───────────────────────────────────────────────────────────────────

@router.post("/rooms", response_model=RoomResponse, status_code=201)
async def create_room(req: RoomCreate):
    _, svc = await _connect_if_needed()
    try:
        return await svc.create_room(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rooms", response_model=RoomListResponse)
async def list_rooms(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    _, svc = await _connect_if_needed()
    rooms, total = await svc.list_rooms(offset, limit)
    return RoomListResponse(rooms=rooms, total=total)


@router.get("/rooms/default", response_model=RoomResponse)
async def get_default_room():
    """Get or create the default room '全员作战室'."""
    _, svc = await _connect_if_needed()
    return await svc.get_or_create_default_room()


@router.get("/rooms/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str):
    _, svc = await _connect_if_needed()
    room = await svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/rooms/{room_id}", response_model=RoomResponse)
async def update_room(room_id: str, req: RoomUpdate):
    _, svc = await _connect_if_needed()
    room = await svc.update_room(room_id, req)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.delete("/rooms/{room_id}", status_code=204)
async def delete_room(room_id: str):
    _, svc = await _connect_if_needed()
    ok = await svc.delete_room(room_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Room not found")


# ─── Messages ────────────────────────────────────────────────────────────────

@router.post("/rooms/{room_id}/messages")
async def send_message(room_id: str, msg: MessageSend):
    _, svc = await _connect_if_needed()
    try:
        user_msg, fan_result = await svc.send_message(room_id, msg)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "user_message": user_msg.model_dump(),
        "fan_out": fan_result.model_dump() if fan_result else None,
    }


@router.get("/rooms/{room_id}/messages", response_model=MessageListResponse)
async def get_messages(
    room_id: str,
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[str] = Query(None),
    since_clear: bool = Query(False,
        description="Only return messages after the most recent context clear"),
):
    _, svc = await _connect_if_needed()
    room = await svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    msgs = await svc.get_messages(room_id, limit, before_id,
                                   since_clear=since_clear)
    total = room.message_count
    has_more = len(msgs) >= limit
    return MessageListResponse(messages=msgs, total=total, has_more=has_more)


# ─── Context Management ────────────────────────────────────────────────────

@router.post("/rooms/{room_id}/context/clear", response_model=ContextClearResponse)
async def clear_context(room_id: str):
    """Insert a context boundary marker. Messages before this point will be
    excluded from default message loading (used for 'clear context' button)."""
    db, svc = await _connect_if_needed()
    room = await svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    result = await svc.clear_context(room_id)
    return ContextClearResponse(**result)


@router.get("/rooms/{room_id}/context/last")
async def get_last_context_clear(room_id: str):
    """Get the most recent context clear marker for a room."""
    db, _ = await _connect_if_needed()
    cc = await db.get_last_context_clear(room_id)
    if not cc:
        raise HTTPException(status_code=404, detail="No context clear found")
    return cc


# ─── Summaries ──────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/summaries", response_model=SummaryListResponse)
async def get_summaries(room_id: str):
    """Get all compression summaries for a room."""
    db, svc = await _connect_if_needed()
    room = await svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    summaries = await db.get_summaries(room_id)
    return SummaryListResponse(
        summaries=[SummaryResponse(**s) for s in summaries],
        total=len(summaries),
    )


@router.post("/rooms/{room_id}/summaries", response_model=SummaryResponse,
             status_code=201)
async def create_summary(room_id: str,
    from_msg_id: str = Query(..., description="First message ID in the range"),
    to_msg_id: str = Query(..., description="Last message ID in the range"),
    summary_text: str = Query(..., description="AI-generated summary text"),
):
    """Store a compression summary for a message range."""
    db, svc = await _connect_if_needed()
    room = await svc.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    result = await svc.create_summary(room_id, summary_text,
                                       from_msg_id, to_msg_id)
    return SummaryResponse(**result)


# ─── Agent Memory ────────────────────────────────────────────────────────────

@router.get("/rooms/{room_id}/memory/{agent_name}", response_model=dict[str, str])
async def get_agent_memory(room_id: str, agent_name: str):
    _, svc = await _connect_if_needed()
    return await svc.get_agent_memory(room_id, agent_name)


@router.post("/rooms/{room_id}/memory/{agent_name}", status_code=204)
async def set_agent_memory(room_id: str, agent_name: str, req: AgentMemoryUpdate):
    _, svc = await _connect_if_needed()
    await svc.set_agent_memory(room_id, agent_name, req.key, req.value)


@router.delete("/rooms/{room_id}/memory/{agent_name}/{key}", status_code=204)
async def delete_agent_memory(room_id: str, agent_name: str, key: str):
    _, svc = await _connect_if_needed()
    ok = await svc.delete_agent_memory(room_id, agent_name, key)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory key not found")


@router.delete("/rooms/{room_id}/memory", status_code=200)
async def clear_room_memory(room_id: str):
    """Clear all agent memories for a room (reset context)."""
    _, svc = await _connect_if_needed()
    deleted = await svc.clear_room_memory(room_id)
    return {"status": "ok", "deleted": deleted}


# ─── User Profile ────────────────────────────────────────────────────────────


class UserProfile(BaseModel):
    name: str = "董事长"
    avatar: str = ""   # base64 data URL
    bio: str = ""


def _load_user() -> UserProfile:
    if USER_FILE.exists():
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserProfile(**data)
        except Exception:
            pass
    return UserProfile()


def _save_user(u: UserProfile) -> None:
    with open(USER_FILE, "w", encoding="utf-8") as f:
        json.dump(u.model_dump(), f, ensure_ascii=False, indent=2)


@router.get("/user", response_model=UserProfile)
async def get_user():
    return _load_user()


@router.put("/user", response_model=UserProfile)
async def update_user(req: UserProfile):
    _save_user(req)
    return req


# ─── Contacts ────────────────────────────────────────────────────────────────


@router.get("/contacts", response_model=list[AgentProfile])
async def list_contacts():
    """List all agents as contacts. (README §2 私聊)"""
    return registry.list()


# ─── Agent Profiles ─────────────────────────────────────────────────────────

@router.get("/agents", response_model=list[AgentProfile])
async def list_agents():
    return registry.list()


@router.post("/agents", response_model=AgentProfile, status_code=201)
async def create_agent(req: AgentCreate):
    """Create a new agent profile, auto-join the default room, and broadcast."""
    # 1. Validate — name must be a valid identifier (lowercase, underscores only)
    raw_name = req.name.strip()
    if not raw_name:
        raise HTTPException(status_code=400, detail="Agent name is required")
    if not raw_name.replace("_", "").isalnum():
        raise HTTPException(status_code=400,
                            detail="Agent name must contain only letters, digits, and underscores")
    if registry.get(raw_name):
        raise HTTPException(status_code=409, detail=f"Agent '{raw_name}' already exists")

    # 2. Create profile directory + config.yaml
    profiles_dir = Path.home() / "AppData" / "Local" / "hermes" / "profiles" / raw_name
    profiles_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "hermes_chat": {
            "system_prompt": req.system_prompt,
            "role": req.role or raw_name,
        }
    }
    with open(profiles_dir / "config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)

    # 3. Reload registry to pick up the new agent
    registry.reload()

    # 4. Auto-join the default room
    _, svc = await _connect_if_needed()
    default_room = await svc.get_or_create_default_room()
    # Add the new agent to default room agents
    all_agents = list(set(default_room.agents + [raw_name]))
    await svc.update_room(default_room.id,
                          RoomUpdate(agents=all_agents))

    # Return the new profile
    profile = registry.get(raw_name)
    if not profile:
        raise HTTPException(status_code=500, detail="Agent created but not found in registry")
    return profile


@router.get("/agents/{name}", response_model=AgentProfile)
async def get_agent(name: str):
    profile = registry.get(name)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    return profile


class AgentUpdate(BaseModel):
    system_prompt: Optional[str] = None
    role: Optional[str] = None


@router.put("/agents/{name}", response_model=AgentProfile)
async def update_agent(name: str, req: AgentUpdate):
    """Update agent SOUL / system_prompt — writes to profile config.yaml."""
    profile = registry.get(name)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")

    profiles_dir = Path.home() / "AppData" / "Local" / "hermes" / "profiles" / name
    if not profiles_dir.exists():
        raise HTTPException(status_code=404, detail=f"Profile dir not found: {profiles_dir}")

    config_path = profiles_dir / "config.yaml"

    # Read existing config (or start fresh)
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Update hermes_chat section
    hc = config.get("hermes_chat", {})
    if req.system_prompt is not None:
        hc["system_prompt"] = req.system_prompt
    if req.role is not None:
        hc["role"] = req.role
    config["hermes_chat"] = hc

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)

    # Reload registry to pick up changes
    registry.reload()
    updated = registry.get(name)
    if not updated:
        raise HTTPException(status_code=500, detail="Agent updated but not found after reload")
    return updated


@router.delete("/agents/{name}", status_code=204)
async def delete_agent(name: str):
    """Delete an agent profile — removes profile dir and config.yaml."""
    profile = registry.get(name)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Remove profile directory
    import shutil
    profiles_dir = Path.home() / "AppData" / "Local" / "hermes" / "profiles" / name
    if profiles_dir.exists():
        shutil.rmtree(profiles_dir, ignore_errors=True)

    # Remove from registry
    registry.unregister(name)

    # Also remove from all rooms
    _, svc = await _connect_if_needed()
    rooms, _ = await svc.list_rooms()
    for room in rooms:
        if name in room.agents:
            new_agents = [a for a in room.agents if a != name]
            if new_agents:
                await svc.update_room(room.id,
                                      RoomUpdate(agents=new_agents))
            else:
                # Room has no agents left — delete it
                await svc.delete_room(room.id)


# ─── Auto-initialize on import ──────────────────────────────────────────────
# The Dashboard imports this module but never calls init_plugin().
# Initialize immediately so DB endpoints work on first request.
init_plugin()
