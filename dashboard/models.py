"""
Hermes Chat — Pydantic schemas.
Mathematical precision: every field is typed, optionality is explicit,
and serialization is lossless.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ───────────────────────────────────────────────────────────────────

class MessageType(str, Enum):
    user = "user"
    agent = "agent"
    system = "system"


class AgentDecision(str, Enum):
    must_reply = "must_reply"      # @mentioned
    may_reply = "may_reply"        # broadcast, self-decides
    skip = "skip"                  # irrelevant


# ─── Room ────────────────────────────────────────────────────────────────────

class RoomCreate(BaseModel):
    """Request: create a new room."""
    name: str = Field(..., min_length=1, max_length=128, description="Room display name")
    agents: list[str] = Field(..., min_length=1, max_length=16,
                              description="Agent member names")


class RoomUpdate(BaseModel):
    """Request: update room metadata."""
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    agents: Optional[list[str]] = Field(None, min_length=1, max_length=16)


class RoomResponse(BaseModel):
    """Response: a room as seen by API consumers."""
    id: str
    name: str
    agents: list[str]
    is_default: bool = False
    created_at: str  # ISO-8601
    updated_at: str  # ISO-8601
    message_count: int = 0

    model_config = {"from_attributes": True}


class RoomListResponse(BaseModel):
    rooms: list[RoomResponse]
    total: int


# ─── Message ─────────────────────────────────────────────────────────────────

class MessageSend(BaseModel):
    """Request: user sends a message into a room."""
    content: str = Field(..., min_length=1, max_length=4096,
                         description="Message text")
    sender: str = Field(..., min_length=1, max_length=64,
                        description="User or system identifier")
    reply_depth: int = Field(0, ge=0, le=1,
                              description="Reply depth (0=user msg, 1=agent reply)")

    @field_validator("content")
    @classmethod
    def parse_mentions(cls, v: str) -> str:
        """No-op validation — mentions are parsed at the routing layer."""
        return v


class MessageResponse(BaseModel):
    """Response: a single message."""
    id: str
    room_id: str
    sender: str
    content: str
    msg_type: MessageType
    target_agent: Optional[str] = None
    reply_depth: int = 0
    timestamp: str  # ISO-8601

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int
    has_more: bool = True  # whether older messages exist


class ContextClearResponse(BaseModel):
    id: str
    room_id: str
    cleared_at: str
    messages_before: int  # how many messages were archived


class SummaryResponse(BaseModel):
    id: str
    room_id: str
    summary_text: str
    from_msg_id: Optional[str] = None
    to_msg_id: Optional[str] = None
    msg_count: int = 0
    created_at: str


class SummaryListResponse(BaseModel):
    summaries: list[SummaryResponse]
    total: int


# ─── Agent ───────────────────────────────────────────────────────────────────

class AgentProfile(BaseModel):
    """Read-only: what the system knows about an agent."""
    name: str
    role: str
    system_prompt: str
    is_active: bool = True


class AgentCreate(BaseModel):
    """Request: create a new agent profile from the Dashboard."""
    name: str = Field(..., min_length=1, max_length=64,
                      description="Agent internal name (used as profile dir name)")
    role: str = Field("", max_length=128,
                      description="Display role / title")
    system_prompt: str = Field(..., min_length=1, max_length=65536,
                                description="Agent SOUL / system prompt")


class AgentMemoryUpdate(BaseModel):
    """Request: persist a memory key-value for an agent in a room."""
    key: str = Field(..., max_length=128)
    value: str = Field(..., max_length=65536)


# ─── Routing / Fan-out ───────────────────────────────────────────────────────

class RoutingDecision(BaseModel):
    """Internal: which agents should receive a message."""
    agent_name: str
    decision: AgentDecision
    reason: str = ""


class AgentTaskInput(BaseModel):
    """Internal: what gets sent to each agent's reasoning sandbox."""
    message_id: str
    room_id: str
    room_name: str
    sender: str
    content: str
    target_agent: Optional[str] = None  # @mention target
    parent_depth: int = 0  # depth of triggering message; agent reply = parent_depth + 1
    history: list[MessageResponse] = Field(default_factory=list,
                                            description="Recent room history")
    agent_memory: dict[str, str] = Field(default_factory=dict,
                                          description="Agent's persisted memory")
    kanban_snapshot: str = ""
    self_profile: AgentProfile | None = None
    member_profiles: list[AgentProfile] = Field(default_factory=list)


class AgentTaskOutput(BaseModel):
    """Internal: an agent's reply (or skip decision)."""
    agent_name: str
    replied: bool
    content: str = ""
    finished_at: str = ""
    timeout: bool = False
    error: str = ""


class FanOutResult(BaseModel):
    """Response after fan-out: all agent replies collected."""
    message_id: str
    responses: list[AgentTaskOutput]
    total_responded: int
    total_timeout: int
    elapsed_ms: int


# ─── Health / Status ─────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    uptime_sec: float = 0.0
    room_count: int = 0
    agent_count: int = 0
    active_connections: int = 0


# ─── Internal helpers ────────────────────────────────────────────────────────

def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
