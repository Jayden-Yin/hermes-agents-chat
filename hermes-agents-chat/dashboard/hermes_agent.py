"""
Hermes Chat — Real Hermes Agent (Dashboard Plugin).

Replaces llm_agent.py with actual Hermes Agent instances that use
the full agent loop: tools (file, terminal, code), memory, skills,
and profile-specific config.

Each agent runs under its own Hermes profile via context-local
HERMES_HOME override, so ma_yilong uses ma_yilong's config/skills,
ma_zhuanzhu uses ma_zhuanzhu's, etc.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Optional

from agent_manager import registry
from models import AgentProfile, AgentTaskInput, AgentTaskOutput, now_iso

logger = logging.getLogger(__name__)

# ─── Profile paths ──────────────────────────────────────────────────────────

_HERMES_PROFILES_DIR = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

# Map agent names to their Hermes profiles (same name by default)
AGENT_PROFILE_MAP = {
    "ma_yilong": "ma_yilong",
    "ma_zhuanzhu": "ma_zhuanzhu",
    "zhang_xiaohu": "zhang_xiaohu",
    "ma_taike": "ma_taike",
}


def _get_profile_path(agent_name: str) -> Path:
    """Get the Hermes profile directory for an agent."""
    profile_name = AGENT_PROFILE_MAP.get(agent_name, agent_name)
    return _HERMES_PROFILES_DIR / profile_name


def _load_system_prompt(agent_name: str) -> str:
    """Read system prompt from profile config.yaml (same source as Dashboard SOUL)."""
    import yaml
    config_path = _get_profile_path(agent_name) / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            return cfg.get("hermes_chat", {}).get("system_prompt", "")
        except Exception:
            pass
    return ""


def _load_user_profile() -> dict:
    """Read user profile from user.json (same file as plugin_api.py uses)."""
    import json
    user_file = Path.home() / "AppData" / "Local" / "hermes" / "chat" / "user.json"
    if user_file.exists():
        try:
            with open(user_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"name": "User", "avatar": "", "bio": ""}


# ─── Hermes Agent ────────────────────────────────────────────────────────────

# Thread pool for running agent loops (AIAgent is synchronous).
# Bumped to 8 workers to reduce risk of deadlock from hung API calls.
# Note: Python threads cannot be forcibly killed — if an agent's
# run_conversation() hangs on a network call, that worker is lost
# until the OS-level TCP timeout fires.
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8)
_EXECUTOR_SEMAPHORE = threading.BoundedSemaphore(8)


class HermesAgent:
    """
    A real Hermes agent that runs the full AIAgent loop with tools,
    memory, and profile-specific configuration.

    Each instance is bound to a specific agent name and profile.
    """

    def __init__(self, name: str, timeout: float = 60.0) -> None:
        self.name = name
        self.timeout = timeout
        self._profile_path = _get_profile_path(name)
        if not self._profile_path.exists():
            logger.warning("Profile not found for %s: %s", name, self._profile_path)

    async def reason(self, ctx: AgentTaskInput) -> AgentTaskOutput:
        """Run the agent in a thread with full conversation history."""

        # Build enriched prompt: memory + kanban + user bio + current message
        prompt_parts = []

        # User profile (so agent knows who it's talking to)
        user = _load_user_profile()
        if user.get("bio"):
            prompt_parts.append(
                "👤 **About the user you are talking to:**\n"
                f"  Name: {user.get('name', 'User')}\n"
                f"  Bio: {user['bio']}"
            )

        # Agent persistent memory (per-room KV store)
        if ctx.agent_memory:
            mem_lines = ["📝 **Your Memory (persisted across conversations):**"]
            for k, v in ctx.agent_memory.items():
                mem_lines.append(f"  • {k}: {v}")
            prompt_parts.append("\n".join(mem_lines))

        # Kanban snapshot (inject active tasks assigned to this agent)
        if (ctx.kanban_snapshot
                and "[kanban:" not in ctx.kanban_snapshot
                and "no pending tasks" not in ctx.kanban_snapshot):
            prompt_parts.append(ctx.kanban_snapshot)

        # Room context — natural format, no [name]: prefix
        prompt_parts.append(
            f"📢 来自「{ctx.room_name}」— {ctx.sender} 说：{ctx.content}"
        )

        prompt = "\n\n---\n\n".join(prompt_parts)

        # Load profile system prompt + inject self-assessment rules
        system_prompt = _load_system_prompt(self.name)

        # Detect DM (1-on-1): if the room has only 1 agent, it's a private chat.
        # In DM, the agent should ALWAYS respond — no self-censoring.
        is_dm = len(ctx.member_profiles) <= 1

        _DM_RULES = """\n\n---\n## 私聊规则\n这是一对一私聊。你是唯一的回复对象。请直接、认真地回复用户的每一条消息。\n不要沉默，不要等待"别人"——这里没有别人，只有你。"""

        _SELF_ASSESS = """\n\n---\n## 群聊规则\n1. 你只代表你自己发言，严禁替其他 Agent 说话或转述他人的话。\n2. 回复中不要加 `[你的名字]:` 前缀——直接说内容即可。\n3. 收到未 @ 你的消息时，依次自问：\n   a. 跟我直接相关吗？\n   b. 我有新信息可以贡献吗？\n   c. 别人回复后我有补充吗？\n   三条全不满足 → 静默，不要回复。"""

        system_prompt = (system_prompt or "") + (_DM_RULES if is_dm else _SELF_ASSESS)

        # Build conversation history in OpenAI format.
        # Use 'name' field on assistant messages so the model knows
        # WHO said what — prevents one agent from echoing others.
        conv_history = []
        if ctx.history:
            for msg in ctx.history[-100:]:
                sender = msg.sender if hasattr(msg, 'sender') else msg.get('sender', 'unknown')
                content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
                if sender == 'user':
                    conv_history.append({"role": "user", "content": content})
                else:
                    conv_history.append({
                        "role": "assistant",
                        "content": content,
                        "name": sender,
                    })

        try:
            # Warn if thread pool is near saturation
            if not _EXECUTOR_SEMAPHORE.acquire(blocking=False):
                logger.warning(
                    "[hermes-agent] Thread pool saturated (%d workers busy) — "
                    "agent %s queued, reply may be delayed",
                    _EXECUTOR._max_workers, self.name,
                )
                _EXECUTOR_SEMAPHORE.acquire()
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    _EXECUTOR,
                    _run_agent_sync,
                    self.name,
                    str(self._profile_path),
                    prompt,
                    system_prompt,
                    conv_history,
                    self.timeout,
                )
            finally:
                _EXECUTOR_SEMAPHORE.release()

            if result.get("error"):
                return AgentTaskOutput(
                    agent_name=self.name,
                    replied=False,
                    content="",
                    finished_at=now_iso(),
                    timeout=False,
                    error=f"❌ {result['error']}",
                )

            return AgentTaskOutput(
                agent_name=self.name,
                replied=bool(result.get("content")),
                content=result.get("content", ""),
                finished_at=now_iso(),
                timeout=result.get("timeout", False),
                error="",
            )

        except Exception as exc:
            logger.error("[hermes-agent] %s failed: %s", self.name, exc)
            return AgentTaskOutput(
                agent_name=self.name,
                replied=False,
                content="",
                finished_at=now_iso(),
                timeout=False,
                error=str(exc),
            )

    async def close(self) -> None:
        pass  # Thread pool is shared


# ─── Synchronous agent runner (runs in thread pool) ─────────────────────────

def _run_agent_sync(
    agent_name: str,
    profile_path: str,
    prompt: str,
    system_prompt: str,
    conversation_history: list,
    timeout: float,
) -> dict:
    """
    Run a Hermes agent synchronously in a thread with full conversation history.

    Uses context-local HERMES_HOME override so each thread sees
    the correct profile's config, skills, and data.
    """
    try:
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        import yaml

        token = set_hermes_home_override(profile_path)

        try:
            config_path = Path(profile_path) / "config.yaml"
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            model_cfg = config.get("model", {})
            api_key = model_cfg.get("api_key", "")
            provider = model_cfg.get("provider", "deepseek")
            model = model_cfg.get("default", "deepseek-chat")
            base_url = model_cfg.get("base_url", "") or None

            from run_agent import AIAgent

            agent = AIAgent(
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                model=model,
                max_iterations=30,
                enabled_toolsets=["hermes-cli"],
                skip_context_files=False,
                skip_memory=False,
            )

            # Run with full conversation history for multi-turn context
            result = agent.run_conversation(
                user_message=prompt,
                system_message=system_prompt if system_prompt else None,
                conversation_history=conversation_history if conversation_history else None,
            )

            return {"content": result.get("final_response", ""), "timeout": False}

        finally:
            reset_hermes_home_override(token)

    except Exception as exc:
        logger.error("[hermes-agent] Error running agent %s: %s", agent_name, exc)
        return {"error": str(exc), "content": "", "timeout": False}


# ─── Factory ─────────────────────────────────────────────────────────────────

def create_hermes_agents(names: list[str]) -> dict[str, HermesAgent]:
    """Create HermesAgent instances for the given agent names."""
    agents: dict[str, HermesAgent] = {}
    for name in names:
        profile = registry.get(name)
        if profile:
            agents[name] = HermesAgent(name=name)
        else:
            registry.register(AgentProfile(
                name=name,
                role=name.title(),
                system_prompt=f"You are {name}, a helpful AI assistant.",
                is_active=True,
            ))
            agents[name] = HermesAgent(name=name)
    return agents
