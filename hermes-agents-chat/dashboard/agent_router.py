"""
Hermes Chat — Agent Message Router.
The crown jewel: handles message routing decisions, parallel fan-out to agents,
timeout control, and result aggregation.

Routing logic:
  • User message enters → parse @mentions
  • @agent X (or @all) → X must reply
  • No @mention → broadcast to all agents → each self-decides relevance
  • Fan-out to target agents in parallel (asyncio.gather with per-task timeout)
  • Results collected in completion order (as they finish, not agent order)
  • Rate limit: max 5 agent replies/min per room

Architecture:
  ┌──────────┐    parse @    ┌──────────────┐   fan-out    ┌─────────────┐
  │ Incoming │ ────────────→ │ Routing      │ ───────────→ │ Agent 1     │
  │ Message  │    mention    │ Decision     │   parallel   │ (sandbox)   │
  └──────────┘               └──────────────┘              │ Agent 2     │
                                   │                        │ (sandbox)   │
                                   ▼                        │ Agent N     │
                              ┌──────────────┐              │ (sandbox)   │
                              │ Rate Limiter │              └─────────────┘
                              │ (5/min/room) │                    │
                              └──────────────┘                    ▼
                                                           ┌──────────────┐
                                                           │ Collect in   │
                                                           │ completion   │
                                                           │ order        │
                                                           └──────────────┘
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

from agent_manager import build_agent_context, registry
from database import Database
from hermes_agent import HermesAgent, create_hermes_agents
from models import (
    AgentDecision,
    AgentTaskInput,
    AgentTaskOutput,
    FanOutResult,
    MessageSend,
    now_iso,
)
from rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

AGENT_TIMEOUT_SEC = 30.0  # max wait per agent
MAX_HISTORY = 50          # max messages injected into reasoning context
MAX_REPLY_TOKENS = 2048   # reply token limit (character-based approximation)


# ─── @mention Parser ─────────────────────────────────────────────────────────

_MENTION_RE = re.compile(r"@(\w[\w.-]{0,31})")


def parse_mentions(text: str, available_agents: set[str]) -> set[str]:
    """
    Extract @mentions from *text* that match known agent names.

    Returns the set of mentioned agent names.
    Special: @all → all available agents.
    """
    raw = set(_MENTION_RE.findall(text))
    if "all" in raw or "everyone" in raw:
        return set(available_agents)
    return raw & available_agents


# ─── Routing Decision ────────────────────────────────────────────────────────

def decide_targets(
    content: str,
    sender: str,
    room_agents: list[str],
    sender_is_user: bool = True,
) -> tuple[set[str], set[str]]:
    """
    Determine which agents should receive this message.

    Routing rules (v0.3):
      • User sender + @mention → mentioned agents *must* reply
      • User sender + no @mention → all agents *may* reply (self-decide relevance)
      • Agent sender + @mention → mentioned agents *may* reply (suggestion, not mandatory)
      • Agent sender + no @mention → all agents *may* reply (broadcast, self-decide)
      • @mention to "user" is always a suggestion (user doesn't reply via API)

    Returns (must_reply, may_reply) where:
      must_reply — agents that MUST respond (only user @mention)
      may_reply  — agents that MAY respond (self-decide relevance)
    """
    available = set(room_agents)
    mentioned = parse_mentions(content, available)

    if not sender_is_user:
        # Agent sender: @mention is suggestion-only → all are may_reply
        # Exclude sender from replying to itself
        may_reply = (mentioned | (available - mentioned)) - {sender}
        return set(), may_reply

    if mentioned:
        # User @mentioned agents *must* reply; rest are optional
        return mentioned, available - mentioned
    else:
        # Broadcast: all agents may reply (self-decide relevance)
        return set(), available


# ─── Parallel Fan-Out ────────────────────────────────────────────────────────

async def _run_single_agent(
    mock_agent: HermesAgent,
    ctx: AgentTaskInput,
    timeout: float,
) -> AgentTaskOutput:
    """
    Run a single agent's reasoning with timeout.

    Returns a completed AgentTaskOutput — either the agent's reply,
    a timeout marker, or an error marker. Never raises.
    """
    try:
        output = await asyncio.wait_for(
            mock_agent.reason(ctx),
            timeout=timeout,
        )
        # Enforce reply length limit
        if output.replied and len(output.content) > MAX_REPLY_TOKENS:
            output.content = output.content[:MAX_REPLY_TOKENS] + "\n\n[...截断]"
        return output
    except asyncio.TimeoutError:
        logger.warning("Agent %s timed out after %.1fs", mock_agent.name, timeout)
        return AgentTaskOutput(
            agent_name=mock_agent.name,
            replied=False,
            content="",
            finished_at=now_iso(),
            timeout=True,
            error=f"⏱ 超时未回复（{timeout:.0f}秒）",
        )
    except Exception as exc:
        logger.error("Agent %s crashed: %s", mock_agent.name, exc)
        return AgentTaskOutput(
            agent_name=mock_agent.name,
            replied=False,
            content="",
            finished_at=now_iso(),
            timeout=False,
            error=f"❌ 运行错误：{exc}",
        )


async def fan_out(
    room_id: str,
    room_name: str,
    message: MessageSend,
    db: Database,
    must_reply: set[str],
    may_reply: set[str],
    mock_agents: dict[str, HermesAgent],
    parent_depth: int = 0,
) -> FanOutResult:
    """
    Fan out a message to agents in *must_reply* (forced) and *may_reply* (self-decide).

    Algorithm:
    1. Build reasoning context for each agent (history + memory + kanban + depth)
    2. Launch all tasks concurrently with per-agent timeout
    3. Collect results as they complete (asyncio.as_completed)
    4. Apply rate limiting: only allow up to 5 agent replies/min/room
    5. Return aggregated FanOutResult

    Depth control (v0.3):
      parent_depth is the depth of the triggering message.
      Agent replies will carry depth = parent_depth + 1.
      Chain limit: depth ≤ 1 from user message (max agent→agent = 1 hop).
    """
    start = time.monotonic()
    target_names = must_reply | may_reply

    if not target_names:
        return FanOutResult(
            message_id="",
            responses=[],
            total_responded=0,
            total_timeout=0,
            elapsed_ms=0,
        )

    # Fetch room history — only messages since last context clear
    cc = await db.get_last_context_clear(room_id)
    if cc:
        history_raw = await db.get_messages_since(room_id, cc["cleared_at"], limit=MAX_HISTORY)
    else:
        history_raw = await db.get_messages(room_id, limit=MAX_HISTORY)
    history_raw.reverse()  # chronological order

    # Fetch agent memory for each
    memory_cache: dict[str, dict[str, str]] = {}
    for name in target_names:
        memory_cache[name] = await db.get_memory(name, room_id)

    # Member profiles for context
    member_profiles = registry.profiles_for(list(target_names))

    # Build contexts and tasks
    tasks: list[asyncio.Task[AgentTaskOutput]] = []
    ctx_map: dict[str, AgentTaskInput] = {}

    for name in target_names:
        if name not in mock_agents:
            logger.warning("Agent %s not found in mock pool — skipping", name)
            continue

        ctx = build_agent_context(
            message_id="",
            room_id=room_id,
            room_name=room_name,
            sender=message.sender,
            content=message.content,
            target_agent=name if name in must_reply else None,
            parent_depth=parent_depth,
            history=history_raw,
            agent_name=name,
            agent_memory=memory_cache.get(name, {}),
            member_profiles=member_profiles,
        )
        ctx_map[name] = ctx

        task = asyncio.create_task(
            _run_single_agent(mock_agents[name], ctx, AGENT_TIMEOUT_SEC)
        )
        tasks.append(task)

    # Collect in completion order (asyncio.as_completed)
    responses: list[AgentTaskOutput] = []
    rate_budget = 5  # max agent replies/min/room

    for coro in asyncio.as_completed(tasks):
        output = await coro
        if output.replied:
            if rate_limiter.check(room_id):
                responses.append(output)
            else:
                logger.info("Rate-limited reply from %s in room %s",
                            output.agent_name, room_id)
                responses.append(AgentTaskOutput(
                    agent_name=output.agent_name,
                    replied=False,
                    content="",
                    finished_at=now_iso(),
                    timeout=False,
                    error="🚫 频率限制（每房间每分钟最多 5 条回复）",
                ))
        else:
            responses.append(output)

    # Sort by agent name for deterministic output
    responses.sort(key=lambda r: r.agent_name)

    elapsed = int((time.monotonic() - start) * 1000)

    return FanOutResult(
        message_id="",
        responses=responses,
        total_responded=sum(1 for r in responses if r.replied),
        total_timeout=sum(1 for r in responses if r.timeout),
        elapsed_ms=elapsed,
    )
