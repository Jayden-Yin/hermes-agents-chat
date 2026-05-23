"""
Hermes Chat — Kanban board snapshot integration.
Queries the local Hermes Kanban SQLite database to produce a compact
text snapshot of active tasks, injected into each agent's reasoning context.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Default kanban DB location (Hermes standard).
DEFAULT_KANBAN_DB = os.path.join(
    os.path.expanduser("~"),
    "AppData", "Local", "hermes", "kanban", "kanban.db",
)


def _find_kanban_db() -> str | None:
    """Walk known locations for a kanban SQLite database."""
    candidates = [
        os.environ.get("HERMES_KANBAN_DB"),
        DEFAULT_KANBAN_DB,
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def snapshot(agent_name: str | None = None, max_tasks: int = 10) -> str:
    """
    Return a human-readable snapshot of open kanban tasks.

    If *agent_name* is given, only show tasks assigned to that agent.
    """
    db_path = _find_kanban_db()
    if not db_path:
        logger.debug("No kanban DB found — skipping snapshot")
        return "[kanban: no database found]"

    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if agent_name:
            cursor.execute(
                "SELECT id, title, status, assignee, priority "
                "FROM tasks "
                "WHERE assignee = ? AND status NOT IN ('done', 'archived', 'cancelled') "
                "ORDER BY priority DESC, created_at DESC LIMIT ?",
                (agent_name, max_tasks),
            )
        else:
            cursor.execute(
                "SELECT id, title, status, assignee, priority "
                "FROM tasks "
                "WHERE status NOT IN ('done', 'archived', 'cancelled') "
                "ORDER BY priority DESC, created_at DESC LIMIT ?",
                (max_tasks,),
            )

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "[kanban: no pending tasks]"

        lines = ["📋 Kanban Snapshot:"]
        for r in rows:
            assignee = f"@{r['assignee']}" if r["assignee"] else ""
            lines.append(
                f"  • {r['status']} #{r['id'][:8]} "
                f"\"{r['title']}\" "
                f"{assignee} "
                f"(p{r['priority']})"
            )
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("Kanban snapshot failed: %s", exc)
        return f"[kanban: error — {exc}]"
