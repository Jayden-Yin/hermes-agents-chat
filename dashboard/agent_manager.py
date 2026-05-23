"""
Hermes Chat — Agent Manager (Dashboard Plugin).

Reads agent profiles from each Hermes profile's config.yaml
(hermes_chat.system_prompt). This is the same source used by both
the Dashboard plugin and the CLI — edit config.yaml to change SOUL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from models import AgentProfile
from kanban_integration import snapshot as kanban_snapshot_fn

logger = logging.getLogger(__name__)

_HERMES_PROFILES_DIR = Path.home() / "AppData" / "Local" / "hermes" / "profiles"

_AGENT_NAMES: list[str] = []  # Populated by _discover_profiles()

# Profile names to exclude from the agent list
_EXCLUDED_PROFILES = {"default"}


def _discover_profiles() -> list[str]:
    """Scan the Hermes profiles directory for available agent profiles."""
    names = []
    if _HERMES_PROFILES_DIR.exists():
        for d in sorted(_HERMES_PROFILES_DIR.iterdir()):
            if not d.is_dir():
                continue
            if d.name in _EXCLUDED_PROFILES:
                continue
            config_path = d / "config.yaml"
            if config_path.exists():
                names.append(d.name)
    return names


_ROLE_FALLBACKS = {
    "ma_yilong": "首席架构师 & CEO",
    "ma_zhuanzhu": "CTO & 算法架构师",
    "zhang_xiaohu": "产品经理 (PM)",
    "ma_taike": "自动化测试执行官",
}

_FALLBACK_SOULS = {
    "ma_yilong": "你是马一龙，Hermes 团队的首席架构师兼 CEO。",
    "ma_zhuanzhu": "你是马专注，Hermes 团队的 CTO 兼算法架构师。",
    "zhang_xiaohu": "你是张小虎，Hermes 团队的产品经理。",
    "ma_taike": "你是马太苛，Hermes 团队的自动化测试执行官。",
}


def _load_agent_profile(name: str) -> AgentProfile:
    """Load agent profile from its Hermes config.yaml."""
    config_path = _HERMES_PROFILES_DIR / name / "config.yaml"

    system_prompt = _FALLBACK_SOULS.get(name, f"You are {name}, a Hermes agent.")
    role = _ROLE_FALLBACKS.get(name, name.replace("_", " ").title())

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            hc = cfg.get("hermes_chat", {})
            if hc.get("system_prompt"):
                system_prompt = hc["system_prompt"]
            if hc.get("role"):
                role = hc["role"]
        except Exception as exc:
            logger.warning("Failed to read config for %s: %s", name, exc)

    return AgentProfile(
        name=name,
        role=role,
        system_prompt=system_prompt,
        is_active=True,
    )


class AgentRegistry:
    """Registry of agent profiles, auto-discovered from Hermes profiles."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentProfile] = {}
        self.reload()

    def reload(self) -> None:
        self._agents.clear()
        names = _discover_profiles()
        for name in names:
            self._agents[name] = _load_agent_profile(name)
        # Also add any hardcoded fallbacks not found on disk
        for name in _FALLBACK_SOULS:
            if name not in self._agents:
                self._agents[name] = _load_agent_profile(name)
        logger.info("Agent registry loaded: %d agents", len(self._agents))

    def register(self, profile: AgentProfile) -> None:
        self._agents[profile.name] = profile

    def unregister(self, name: str) -> bool:
        """Remove an agent from the registry. Returns True if removed."""
        if name in self._agents:
            del self._agents[name]
            logger.info("Agent unregistered: %s", name)
            return True
        return False

    def get(self, name: str) -> Optional[AgentProfile]:
        return self._agents.get(name)

    def list(self) -> list[AgentProfile]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def profiles_for(self, agent_names: list[str]) -> list[AgentProfile]:
        return [self._agents[n] for n in agent_names if n in self._agents]


registry = AgentRegistry()


def build_agent_context(
    *,
    message_id: str,
    room_id: str,
    room_name: str,
    sender: str,
    content: str,
    target_agent: Optional[str],
    parent_depth: int = 0,
    history: list[dict],
    agent_name: str,
    agent_memory: dict[str, str],
    member_profiles: list[AgentProfile],
):
    from models import AgentTaskInput, MessageResponse

    profile = registry.get(agent_name)
    history_responses = [MessageResponse(**m) for m in history[-100:]]

    return AgentTaskInput(
        message_id=message_id,
        room_id=room_id,
        room_name=room_name,
        sender=sender,
        content=content,
        target_agent=target_agent,
        parent_depth=parent_depth,
        history=history_responses,
        agent_memory=agent_memory,
        kanban_snapshot=kanban_snapshot_fn(agent_name),
        self_profile=profile,
        member_profiles=member_profiles,
    )
