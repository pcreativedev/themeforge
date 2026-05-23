"""Multi-agent compare module.

Runs the same prompt through multiple AI CLIs (Claude Code, Codex,
Gemini, OpenCode) in parallel and exposes the metadata needed to
render side-by-side comparison panes.

Each CLI is invoked in non-interactive one-shot mode. Output is plain
text (we don't parse stream-json yet — see ROADMAP for token/cost
extraction).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass
class AgentSpec:
    key: str
    name: str
    cli: str                  # binary to check on PATH
    argv_template: list[str]  # "{prompt}" placeholder substituted at runtime
    color: str                # consistent with cost_tracker palette


AGENTS: dict[str, AgentSpec] = {
    "claude": AgentSpec(
        key="claude",
        name="Claude Code",
        cli="claude",
        argv_template=["claude", "-p", "{prompt}"],
        color="#62b4ff",
    ),
    "codex": AgentSpec(
        key="codex",
        name="Codex",
        cli="codex",
        argv_template=["codex", "exec", "{prompt}"],
        color="#86efac",
    ),
    "gemini": AgentSpec(
        key="gemini",
        name="Gemini",
        cli="gemini",
        argv_template=["gemini", "-p", "{prompt}"],
        color="#fbbf24",
    ),
    "opencode": AgentSpec(
        key="opencode",
        name="OpenCode",
        cli="opencode",
        # opencode takes the prompt as a positional arg (`-p` is --password)
        argv_template=["opencode", "run", "{prompt}"],
        color="#c084fc",
    ),
}


def check_agent_available(key: str) -> bool:
    """Returns True if the CLI is on PATH."""
    spec = AGENTS.get(key)
    if not spec:
        return False
    return shutil.which(spec.cli) is not None


def available_agents() -> list[str]:
    """Returns the list of agent keys whose CLI is on PATH."""
    return [k for k in AGENTS if check_agent_available(k)]


def build_argv(key: str, prompt: str) -> list[str]:
    """Returns the argv for invoking the agent in one-shot mode."""
    spec = AGENTS[key]
    return [a.replace("{prompt}", prompt) for a in spec.argv_template]
