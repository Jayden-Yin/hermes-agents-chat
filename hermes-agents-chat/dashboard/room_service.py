"""
Hermes Chat — Room Service.
Business logic layer between HTTP routes and database/routing.

Provides:
  • Room CRUD with validation (no duplicate names, agent existence check)
  • Message sending pipeline (save → route → fan-out → persist replies)
  • Agent memory read/write
"""

from __future__ import annotations

import logging
from typing import Optional

from agent_manager import registry
from agent_router import decide_targets, fan_out
from database import Database
from hermes_agent import HermesAgent, create_hermes_agents
from models import (
    FanOutResult,
    MessageResponse,
    MessageSend,
    MessageType,
    RoomCreate,
    RoomResponse,
    RoomUpdate,
    new_id,
    now_iso,
)

logger = logging.getLogger(__name__)


class RoomService:
    """
    Stateless service — all state lives in *db* and the agent router.

    Mock agents are created on first use per room and cached in-memory.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._mock_agents: dict[str, dict[str, HermesAgent]] = {}  # room_id → agents

    def _get_or_create_hermes_agents(self, room_id: str,
                                    agent_names: list[str]) -> dict[str, HermesAgent]:
        if room_id not in self._mock_agents:
            self._mock_agents[room_id] = create_hermes_agents(agent_names)
        return self._mock_agents[room_id]

    # ── Room CRUD ───────────────────────────────────────────────────────────

    async def create_room(self, req: RoomCreate) -> RoomResponse:
        """Create room. Checks agent names exist in registry."""
        # Validate agent names
        unknown = [a for a in req.agents if a not in registry.names()
                   and a != "user"]
        if unknown:
            raise ValueError(f"Unknown agents: {', '.join(unknown)}")

        now = now_iso()
        rid = new_id()
        room = await self._db.create_room(rid, req.name, req.agents, now, now)

        # Pre-create mock agents for this room
        self._get_or_create_hermes_agents(rid, req.agents)

        return RoomResponse(
            id=room["id"],
            name=room["name"],
            agents=room["agents"],
            is_default=room.get("is_default", False),
            created_at=room["created_at"],
            updated_at=room["updated_at"],
            message_count=0,
        )

    async def get_room(self, room_id: str) -> Optional[RoomResponse]:
        room = await self._db.get_room(room_id)
        if not room:
            return None
        msg_count = await self._db.count_messages(room_id)
        return RoomResponse(
            id=room["id"],
            name=room["name"],
            agents=room["agents"],
            is_default=room.get("is_default", False),
            created_at=room["created_at"],
            updated_at=room["updated_at"],
            message_count=msg_count,
        )

    async def list_rooms(self, offset: int = 0,
                         limit: int = 100) -> tuple[list[RoomResponse], int]:
        rooms = await self._db.list_rooms(offset, limit)
        total = await self._db.count_rooms()
        result: list[RoomResponse] = []
        for r in rooms:
            msg_count = await self._db.count_messages(r["id"])
            result.append(RoomResponse(
                id=r["id"], name=r["name"], agents=r["agents"],
                is_default=r.get("is_default", False),
                created_at=r["created_at"], updated_at=r["updated_at"],
                message_count=msg_count,
            ))
        return result, total

    async def update_room(self, room_id: str,
                          req: RoomUpdate) -> Optional[RoomResponse]:
        room = await self._db.get_room(room_id)
        if not room:
            return None

        old_agents: list[str] = room["agents"]
        new_agents = req.agents if req.agents is not None else old_agents

        # Detect member changes and broadcast system messages
        if req.agents is not None:
            added = [a for a in new_agents if a not in old_agents]
            removed = [a for a in old_agents if a not in new_agents]

            now = now_iso()
            for a in added:
                await self._db.create_message(
                    id=new_id(), room_id=room_id,
                    sender="system",
                    content=f"🟢 Agent @{a} 已加入房间",
                    msg_type=MessageType.system.value,
                    timestamp=now,
                    target_agent=None,
                    reply_depth=0,
                )
            for a in removed:
                await self._db.create_message(
                    id=new_id(), room_id=room_id,
                    sender="system",
                    content=f"🔴 Agent @{a} 已离开房间",
                    msg_type=MessageType.system.value,
                    timestamp=now,
                    target_agent=None,
                    reply_depth=0,
                )

        # Update room in DB
        updated = await self._db.update_room(room_id, req.name, new_agents,
                                              updated_at=now_iso())
        if not updated:
            return None

        # If agents changed, re-create mock agent pool
        if req.agents is not None:
            self._mock_agents[room_id] = create_hermes_agents(new_agents)

        msg_count = await self._db.count_messages(room_id)
        return RoomResponse(
            id=updated["id"], name=updated["name"],
            agents=updated["agents"],
            is_default=updated.get("is_default", False),
            created_at=updated["created_at"],
            updated_at=updated["updated_at"],
            message_count=msg_count,
        )

    async def delete_room(self, room_id: str) -> bool:
        self._mock_agents.pop(room_id, None)
        return await self._db.delete_room(room_id)

    # ── Default Room ─────────────────────────────────────────────────────────

    async def get_or_create_default_room(self) -> RoomResponse:
        """
        Get or create the default room '全员作战室'.

        The default room dynamically includes all registered Hermes agents.
        Created automatically when the user first enters the Chat Tab.
        """
        existing = await self._db.get_default_room()
        if existing:
            # Refresh agents list to include all current agents
            all_agents = registry.names()
            if set(existing["agents"]) != set(all_agents):
                await self._db.update_room_agents(
                    existing["id"], all_agents, now_iso())
                existing["agents"] = all_agents
            msg_count = await self._db.count_messages(existing["id"])
            return RoomResponse(
                id=existing["id"], name=existing["name"],
                agents=existing["agents"],
                is_default=True,
                created_at=existing["created_at"],
                updated_at=now_iso(),
                message_count=msg_count,
            )

        # Create new default room with all registered agents
        all_agents = registry.names()
        rid = new_id()
        now = now_iso()
        room = await self._db.create_room(
            rid, "全员作战室", all_agents, now, now, is_default=True,
        )

        self._get_or_create_hermes_agents(rid, all_agents)

        return RoomResponse(
            id=room["id"], name=room["name"],
            agents=room["agents"],
            is_default=True,
            created_at=room["created_at"],
            updated_at=room["updated_at"],
            message_count=0,
        )

    # ── Messages ────────────────────────────────────────────────────────────

    async def send_message(self, room_id: str,
                           msg: MessageSend) -> tuple[MessageResponse, FanOutResult | None]:
        """
        Full message pipeline (v0.3):

        1. Save user/agent message to DB (with reply_depth)
        2. If reply_depth >= 1, skip fan-out (depth ≤ 1 chain limit)
        3. Determine routing targets (parse @mentions, sender-type-aware)
        4. Fan out to agents in parallel
        5. Save agent replies to DB (depth = parent_depth + 1)
        6. Return (triggering_message, fan_out_result)
        """
        room = await self._db.get_room(room_id)
        if not room:
            raise ValueError(f"Room {room_id} not found")

        # 1. Determine parent depth from the message
        parent_depth = msg.reply_depth

        # 2. Depth guard: if depth >= 1, no further agent fan-out
        if parent_depth >= 1:
            raise ValueError(
                f"Agent chain depth exceeded (depth={parent_depth}, max=1). "
                f"Agents cannot @-mention other agents beyond depth 1."
            )

        sender_is_user = (msg.sender == "user")

        # 3. Save trigger message
        msg_id = new_id()
        ts = now_iso()
        saved = await self._db.create_message(
            id=msg_id, room_id=room_id,
            sender=msg.sender,
            content=msg.content,
            msg_type=MessageType.user.value if sender_is_user else MessageType.agent.value,
            timestamp=ts,
            target_agent=None,
            reply_depth=parent_depth,
        )

        trigger_msg = MessageResponse(
            id=saved["id"], room_id=saved["room_id"],
            sender=saved["sender"], content=saved["content"],
            msg_type=MessageType.user if sender_is_user else MessageType.agent,
            target_agent=saved["target_agent"],
            reply_depth=saved["reply_depth"],
            timestamp=saved["timestamp"],
        )

        # 4. Determine routing
        must_reply, may_reply = decide_targets(
            content=msg.content,
            sender=msg.sender,
            room_agents=room["agents"],
            sender_is_user=sender_is_user,
        )

        # 5. Fan out (with depth tracking)
        mock_agents = self._get_or_create_hermes_agents(room_id, room["agents"])
        fan_result = await fan_out(
            room_id=room_id,
            room_name=room["name"],
            message=msg,
            db=self._db,
            must_reply=must_reply,
            may_reply=may_reply,
            mock_agents=mock_agents,
            parent_depth=parent_depth,
        )

        # 6. Save agent replies with incremented depth
        child_depth = parent_depth + 1
        for resp in fan_result.responses:
            if resp.replied:
                await self._db.create_message(
                    id=new_id(),
                    room_id=room_id,
                    sender=resp.agent_name,
                    content=resp.content,
                    msg_type=MessageType.agent.value,
                    timestamp=resp.finished_at or now_iso(),
                    target_agent=None,
                    reply_depth=child_depth,
                )

        # Update fan_result with the message_id
        fan_result.message_id = msg_id
        return trigger_msg, fan_result

    async def get_messages(self, room_id: str, limit: int = 50,
                           before_id: Optional[str] = None,
                           since_clear: bool = False) -> list[MessageResponse]:
        # If since_clear, find the last context clear timestamp
        if since_clear:
            cc = await self._db.get_last_context_clear(room_id)
            if cc:
                raw = await self._db.get_messages_since(
                    room_id, cc["cleared_at"], limit, before_id)
            else:
                raw = await self._db.get_messages(room_id, limit, before_id)
        else:
            raw = await self._db.get_messages(room_id, limit, before_id)
        return [
            MessageResponse(
                id=r["id"], room_id=r["room_id"],
                sender=r["sender"], content=r["content"],
                msg_type=MessageType(r["msg_type"]),
                target_agent=r["target_agent"],
                reply_depth=r["reply_depth"],
                timestamp=r["timestamp"],
            )
            for r in raw
        ]

    # ── Context Management ─────────────────────────────────────────────────

    async def clear_context(self, room_id: str) -> dict:
        """Insert a context clear marker. Count messages before the clear.
        Also clear all agent memories for the room."""
        now = now_iso()
        cid = new_id()
        # Count messages before this clear
        messages_before = await self._db.count_messages(room_id)
        await self._db.create_context_clear(cid, room_id, now)
        # Also clear agent memories
        await self._db.clear_room_memory(room_id)
        return {"id": cid, "room_id": room_id, "cleared_at": now,
                "messages_before": messages_before}

    # ── Summaries ───────────────────────────────────────────────────────────

    async def create_summary(self, room_id: str, summary_text: str,
                              from_msg_id: str | None = None,
                              to_msg_id: str | None = None) -> dict:
        """Create a compression summary for a message range."""
        sid = new_id()
        now = now_iso()
        msg_count = 0
        # Count messages in range if IDs provided
        if from_msg_id and to_msg_id:
            all_msgs = await self._db.get_messages(room_id, limit=1000)
            in_range = [m for m in all_msgs
                        if from_msg_id <= m["id"] <= to_msg_id]
            msg_count = len(in_range)
        return await self._db.create_summary(
            sid, room_id, summary_text, from_msg_id, to_msg_id,
            msg_count, now)

    # ── Agent Memory ────────────────────────────────────────────────────────

    async def get_agent_memory(self, room_id: str,
                                agent_name: str) -> dict[str, str]:
        return await self._db.get_memory(agent_name, room_id)

    async def set_agent_memory(self, room_id: str, agent_name: str,
                                key: str, value: str) -> None:
        await self._db.set_memory(agent_name, room_id, key, value,
                                   updated_at=now_iso())

    async def delete_agent_memory(self, room_id: str, agent_name: str,
                                   key: str) -> bool:
        return await self._db.delete_memory(agent_name, room_id, key)

    async def clear_room_memory(self, room_id: str) -> int:
        """Clear all agent memories for a room."""
        return await self._db.clear_room_memory(room_id)
