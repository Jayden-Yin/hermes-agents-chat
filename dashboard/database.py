"""
Hermes Chat — SQLite persistence layer.
Zero-dependency SQL (no ORM). Single-file database at a configurable path.
Thread-safe via aiosqlite's connection-per-coroutine model.

Schema:
  rooms        — id, name, agents (JSON array), created_at, updated_at
  messages     — id, room_id (FK), sender, content, msg_type, target_agent, timestamp
  agent_memory — agent_name, room_id, key, value, updated_at (composite PK)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Schema DDL ──────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS rooms (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    agents     TEXT NOT NULL DEFAULT '[]',  -- JSON array of agent names
    is_default INTEGER NOT NULL DEFAULT 0,  -- 1 = default room "全员作战室"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    room_id      TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    sender       TEXT NOT NULL,
    content      TEXT NOT NULL,
    msg_type     TEXT NOT NULL DEFAULT 'user',
    target_agent TEXT,
    reply_depth  INTEGER NOT NULL DEFAULT 0,  -- 0=user, 1+=agent chain depth
    timestamp    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_room_ts
    ON messages(room_id, timestamp);

CREATE TABLE IF NOT EXISTS agent_memory (
    agent_name TEXT NOT NULL,
    room_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_name, room_id, key)
);

-- ── v0.2: Context management ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS context_clears (
    id         TEXT PRIMARY KEY,
    room_id    TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    cleared_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_clears_room
    ON context_clears(room_id, cleared_at DESC);

CREATE TABLE IF NOT EXISTS room_summaries (
    id           TEXT PRIMARY KEY,
    room_id      TEXT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    summary_text TEXT NOT NULL,
    from_msg_id  TEXT,
    to_msg_id    TEXT,
    msg_count    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_room_summaries_room
    ON room_summaries(room_id, created_at);
"""


# ─── Connection Manager ──────────────────────────────────────────────────────

class Database:
    """Singleton-style async SQLite connection wrapper."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(DDL)
        await self._conn.commit()
        logger.info("Database ready at %s (%.0f KB)", self._path,
                     self._path.stat().st_size / 1024 if self._path.exists() else 0)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # ── Rooms ────────────────────────────────────────────────────────────────

    async def create_room(self, id: str, name: str, agents: list[str],
                          created_at: str, updated_at: str,
                          is_default: bool = False) -> dict:
        agents_json = json.dumps(agents, ensure_ascii=False)
        await self._conn.execute(
            "INSERT INTO rooms (id, name, agents, is_default, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (id, name, agents_json, 1 if is_default else 0, created_at, updated_at),
        )
        await self._conn.commit()
        return {"id": id, "name": name, "agents": agents,
                "is_default": is_default,
                "created_at": created_at, "updated_at": updated_at}

    async def get_room(self, room_id: str) -> Optional[dict]:
        row = await self._conn.execute_fetchall(
            "SELECT * FROM rooms WHERE id = ?", (room_id,))
        if not row:
            return None
        return self._row_to_room(row[0])

    async def list_rooms(self, offset: int = 0, limit: int = 100) -> list[dict]:
        rows = await self._conn.execute_fetchall(
            "SELECT * FROM rooms ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset))
        return [self._row_to_room(r) for r in rows]

    async def update_room(self, room_id: str, name: Optional[str] = None,
                          agents: Optional[list[str]] = None,
                          updated_at: str | None = None) -> Optional[dict]:
        existing = await self.get_room(room_id)
        if not existing:
            return None
        final_name = name if name is not None else existing["name"]
        final_agents = agents if agents is not None else existing["agents"]
        final_updated = updated_at if updated_at else existing["updated_at"]
        await self._conn.execute(
            "UPDATE rooms SET name=?, agents=?, updated_at=? WHERE id=?",
            (final_name, json.dumps(final_agents, ensure_ascii=False),
             final_updated, room_id))
        await self._conn.commit()
        return {**existing, "name": final_name, "agents": final_agents,
                "updated_at": final_updated}

    async def delete_room(self, room_id: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM rooms WHERE id = ?", (room_id,))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def count_rooms(self) -> int:
        row = await self._conn.execute_fetchall(
            "SELECT COUNT(*) AS cnt FROM rooms")
        return row[0][0]

    async def get_default_room(self) -> Optional[dict]:
        """Return the default room '全员作战室' if it exists."""
        rows = await self._conn.execute_fetchall(
            "SELECT * FROM rooms WHERE is_default = 1 LIMIT 1")
        if not rows:
            return None
        return self._row_to_room(rows[0])

    async def update_room_agents(self, room_id: str,
                                  agents: list[str],
                                  updated_at: str) -> bool:
        """Atomically update the agents list for a room."""
        cursor = await self._conn.execute(
            "UPDATE rooms SET agents=?, updated_at=? WHERE id=?",
            (json.dumps(agents, ensure_ascii=False), updated_at, room_id))
        await self._conn.commit()
        return cursor.rowcount > 0

    # ── Messages ─────────────────────────────────────────────────────────────

    async def create_message(self, id: str, room_id: str, sender: str,
                             content: str, msg_type: str,
                             timestamp: str,
                             target_agent: Optional[str] = None,
                             reply_depth: int = 0) -> dict:
        await self._conn.execute(
            "INSERT INTO messages (id, room_id, sender, content, msg_type, "
            "target_agent, reply_depth, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (id, room_id, sender, content, msg_type, target_agent, reply_depth, timestamp))
        await self._conn.commit()
        return {"id": id, "room_id": room_id, "sender": sender,
                "content": content, "msg_type": msg_type,
                "target_agent": target_agent, "reply_depth": reply_depth,
                "timestamp": timestamp}

    async def get_messages(self, room_id: str, limit: int = 50,
                           before_id: Optional[str] = None) -> list[dict]:
        if before_id:
            # Paginate: messages older than the given id
            before_ts = await self._conn.execute_fetchall(
                "SELECT timestamp FROM messages WHERE id = ?", (before_id,))
            if not before_ts:
                return []
            rows = await self._conn.execute_fetchall(
                "SELECT * FROM messages WHERE room_id = ? AND timestamp < ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (room_id, before_ts[0][0], limit))
        else:
            rows = await self._conn.execute_fetchall(
                "SELECT * FROM messages WHERE room_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (room_id, limit))
        return [self._row_to_message(r) for r in rows]

    async def count_messages(self, room_id: str) -> int:
        row = await self._conn.execute_fetchall(
            "SELECT COUNT(*) FROM messages WHERE room_id = ?", (room_id,))
        return row[0][0]

    # ── Agent Memory ─────────────────────────────────────────────────────────

    async def set_memory(self, agent_name: str, room_id: str,
                         key: str, value: str, updated_at: str) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO agent_memory "
            "(agent_name, room_id, key, value, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_name, room_id, key, value, updated_at))
        await self._conn.commit()

    async def get_memory(self, agent_name: str, room_id: str) -> dict[str, str]:
        rows = await self._conn.execute_fetchall(
            "SELECT key, value FROM agent_memory "
            "WHERE agent_name = ? AND room_id = ?",
            (agent_name, room_id))
        return {r[0]: r[1] for r in rows}

    async def delete_memory(self, agent_name: str, room_id: str,
                            key: str) -> bool:
        cursor = await self._conn.execute(
            "DELETE FROM agent_memory WHERE agent_name=? AND room_id=? AND key=?",
            (agent_name, room_id, key))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def clear_room_memory(self, room_id: str) -> int:
        """Delete all agent memories for a room. Returns count of deleted rows."""
        cursor = await self._conn.execute(
            "DELETE FROM agent_memory WHERE room_id=?", (room_id,))
        await self._conn.commit()
        return cursor.rowcount

    # ── Context Clears ───────────────────────────────────────────────────────

    async def create_context_clear(self, id: str, room_id: str,
                                   cleared_at: str) -> dict:
        await self._conn.execute(
            "INSERT INTO context_clears (id, room_id, cleared_at) VALUES (?, ?, ?)",
            (id, room_id, cleared_at))
        await self._conn.commit()
        return {"id": id, "room_id": room_id, "cleared_at": cleared_at}

    async def get_last_context_clear(self, room_id: str) -> Optional[dict]:
        rows = await self._conn.execute_fetchall(
            "SELECT * FROM context_clears WHERE room_id = ? "
            "ORDER BY cleared_at DESC LIMIT 1", (room_id,))
        if not rows:
            return None
        r = rows[0]
        return {"id": r["id"], "room_id": r["room_id"], "cleared_at": r["cleared_at"]}

    async def get_messages_since(self, room_id: str,
                                  since: str, limit: int = 50,
                                  before_id: Optional[str] = None) -> list[dict]:
        """Get messages after `since` timestamp, with optional pagination."""
        if before_id:
            before_ts = await self._conn.execute_fetchall(
                "SELECT timestamp FROM messages WHERE id = ?", (before_id,))
            if not before_ts:
                return []
            rows = await self._conn.execute_fetchall(
                "SELECT * FROM messages WHERE room_id = ? "
                "AND timestamp >= ? AND timestamp < ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (room_id, since, before_ts[0][0], limit))
        else:
            rows = await self._conn.execute_fetchall(
                "SELECT * FROM messages WHERE room_id = ? "
                "AND timestamp >= ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (room_id, since, limit))
        return [self._row_to_message(r) for r in rows]

    # ── Room Summaries ────────────────────────────────────────────────────────

    async def create_summary(self, id: str, room_id: str,
                              summary_text: str, from_msg_id: str | None,
                              to_msg_id: str | None, msg_count: int,
                              created_at: str) -> dict:
        await self._conn.execute(
            "INSERT INTO room_summaries "
            "(id, room_id, summary_text, from_msg_id, to_msg_id, msg_count, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id, room_id, summary_text, from_msg_id, to_msg_id, msg_count, created_at))
        await self._conn.commit()
        return {"id": id, "room_id": room_id, "summary_text": summary_text,
                "from_msg_id": from_msg_id, "to_msg_id": to_msg_id,
                "msg_count": msg_count, "created_at": created_at}

    async def get_summaries(self, room_id: str) -> list[dict]:
        rows = await self._conn.execute_fetchall(
            "SELECT * FROM room_summaries WHERE room_id = ? "
            "ORDER BY created_at", (room_id,))
        return [{"id": r["id"], "room_id": r["room_id"],
                 "summary_text": r["summary_text"],
                 "from_msg_id": r["from_msg_id"], "to_msg_id": r["to_msg_id"],
                 "msg_count": r["msg_count"], "created_at": r["created_at"]}
                for r in rows]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_room(row: aiosqlite.Row) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "agents": json.loads(row["agents"]),
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_message(row: aiosqlite.Row) -> dict:
        return {
            "id": row["id"],
            "room_id": row["room_id"],
            "sender": row["sender"],
            "content": row["content"],
            "msg_type": row["msg_type"],
            "target_agent": row["target_agent"],
            "reply_depth": row["reply_depth"],
            "timestamp": row["timestamp"],
        }
