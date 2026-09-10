"""Common interface every judge backend implements."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class JudgeRunResult:
    #: The agent's final free-text message (informational -- the authoritative
    #: verdict is whatever ended up written to <output_dir>/verdicts.json).
    raw_output: str
    transcript: List[Any] = field(default_factory=list)
    error: Optional[str] = None


class JudgeBackend:
    """Runs one agent session: a system prompt plus a task prompt, optionally
    with the judge MCP tool server attached.
    """

    def run(
        self,
        system_prompt: str,
        task_prompt: str,
        case_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        tools_enabled: bool = False,
        allowed_mcp_tools: Optional[List[str]] = None,
    ) -> JudgeRunResult:
        """Run one session.

        ``case_dir``/``output_dir`` are only required when ``tools_enabled``
        is True -- they are passed straight through to
        ``tools_server.py <case_dir> <output_dir>``.

        ``allowed_mcp_tools``, when given, restricts which of the judge MCP
        server's tools (short names, e.g. ``["read_file", "write_file"]``)
        the agent is actually allowed to call -- the server still exposes
        all four; this only narrows the CLI-level allowlist. ``None`` means
        every tool the server exposes is allowed (the existing behaviour).
        """
        raise NotImplementedError
