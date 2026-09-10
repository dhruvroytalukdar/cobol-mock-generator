"""ClaudeCLIBackend: headless ``claude -p``, the same invocation pattern this
project already uses in ``testgen/generate_testcases.py`` (prompt piped over
stdin, never argv, to sidestep Windows' ~32K-char command-line limit).

Two things make this a strict, reproducible sandbox rather than a normal
Claude Code session:

* ``--restricted`` + an explicit ``--disallowedTools`` for every ambient
  built-in tool -- without this, Read/Glob/Grep would still be reachable
  (just confined to the working directory), which is exactly ``transformed/``
  and ``modification_quantity/`` here: enough to leak ground truth.
* ``--strict-mcp-config`` (treatment only) -- the *only* tools available are
  the four from the judge's own MCP server, nothing from project/user
  settings.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import List, Optional

from .base import JudgeBackend, JudgeRunResult

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
MCP_SERVER_NAME = "judge_tools"
MCP_TOOL_NAMES = [
    f"mcp__{MCP_SERVER_NAME}__read_file",
    f"mcp__{MCP_SERVER_NAME}__get_failing_testcases",
    f"mcp__{MCP_SERVER_NAME}__get_coverage",
    f"mcp__{MCP_SERVER_NAME}__write_file",
]

# Every ambient built-in worth naming explicitly -- unknown names are simply
# ignored, so it's safe to over-list rather than risk missing one.
_BUILTIN_TOOLS_TO_DENY = [
    "Bash", "BashOutput", "KillShell", "PowerShell",
    "Read", "Write", "Edit", "NotebookEdit",
    "Glob", "Grep", "WebFetch", "WebSearch",
    "Task", "Agent", "TodoWrite", "ExitPlanMode", "AskUserQuestion",
    "Skill", "Artifact", "ScheduleWakeup", "SendFeedback",
    # Cross-session/orchestration tools -- an agent that finds itself without
    # its expected tools must fail visibly, not go looking for a peer session
    # to offload the task to (this happened once during development).
    "SendMessage", "ListAgents", "TaskCreate", "TaskGet", "TaskList",
    "TaskUpdate", "TaskOutput", "TaskStop", "EnterWorktree", "ExitWorktree",
    "DesignSync", "PushNotification", "RemoteTrigger", "CronCreate",
    "CronList", "CronDelete", "EndConversation",
]


class ClaudeCLIBackend(JudgeBackend):
    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        effort: str = "low",
        claude_bin: str = "claude",
        timeout: int = 900,
    ):
        self.model = model
        self.effort = effort
        self.claude_bin = claude_bin
        self.timeout = timeout

    def run(
        self,
        system_prompt: str,
        task_prompt: str,
        case_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        tools_enabled: bool = False,
        allowed_mcp_tools: Optional[List[str]] = None,
    ) -> JudgeRunResult:
        cmd: List[str] = [
            self.claude_bin, "-p",
            "--model", self.model,
            "--effort", self.effort,
            "--restricted",
            # NOTE: deliberately NOT --safe-mode -- its own help text says it
            # disables "MCP servers" among other customizations, which
            # silently strips the judge tools out from under the treatment
            # condition (confirmed by hand: identical invocation with
            # --safe-mode added drops every mcp__judge_tools__* tool from
            # the agent's tool list). --restricted already gives the
            # sandboxing this backend needs (no Bash/PowerShell/WebFetch,
            # file tools confined to working directories, no
            # bypassPermissions).
            "--no-session-persistence",
            "--system-prompt", system_prompt,
            "--disallowedTools", *_BUILTIN_TOOLS_TO_DENY,
        ]

        mcp_config_path = None
        if tools_enabled:
            if not (case_dir and output_dir):
                raise ValueError("tools_enabled requires case_dir and output_dir")
            mcp_config_path = self._write_mcp_config(case_dir, output_dir)
            if allowed_mcp_tools is not None:
                allowed = [f"mcp__{MCP_SERVER_NAME}__{name}" for name in allowed_mcp_tools]
            else:
                allowed = MCP_TOOL_NAMES
            # NOTE: --strict-mcp-config combined with --restricted disables
            # MCP servers entirely (see --restricted's own help text: "add
            # --strict-mcp-config to skip MCP servers too") -- the opposite
            # of --strict-mcp-config's standalone meaning ("only use MCP
            # servers from --mcp-config"). Omitted here on purpose; there is
            # no project/user .mcp.json in this repo to isolate from anyway.
            #
            # The MCP server (tools_server.py) always registers all four
            # tools regardless of allowed_mcp_tools -- narrowing --allowedTools
            # is what actually keeps the agent from calling the others; it
            # never even sees them listed.
            cmd += [
                "--mcp-config", mcp_config_path,
                "--allowedTools", *allowed,
            ]

        try:
            try:
                proc = subprocess.run(
                    cmd, input=task_prompt, cwd=os.getcwd(),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                # Handled here rather than left to propagate: a direct,
                # single-case invocation of this backend must fail with a
                # clean JudgeRunResult like every other error path, not an
                # uncaught traceback (a batch run already survives this via
                # run_batch.py's own exception isolation, but this backend
                # should not depend on being called through that wrapper).
                stdout = exc.stdout or ""
                return JudgeRunResult(
                    raw_output=stdout,
                    error=f"claude timed out after {self.timeout}s",
                )
        finally:
            if mcp_config_path and os.path.exists(mcp_config_path):
                os.remove(mcp_config_path)

        if proc.returncode != 0:
            return JudgeRunResult(
                raw_output=proc.stdout,
                error=f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[:2000]}",
            )
        return JudgeRunResult(raw_output=proc.stdout)

    @staticmethod
    def _write_mcp_config(case_dir: str, output_dir: str) -> str:
        # ``python -m cobol_transformer...`` only resolves when the process's
        # cwd is the repo root (the package isn't pip-installed) -- the
        # claude CLI does not guarantee that cwd for spawned MCP servers, so
        # PYTHONPATH is set explicitly instead of relying on it.
        config = {
            "mcpServers": {
                MCP_SERVER_NAME: {
                    "command": sys.executable,
                    "args": [
                        "-m", "cobol_transformer.judge.tools_server",
                        os.path.abspath(case_dir), os.path.abspath(output_dir),
                    ],
                    "env": {"PYTHONPATH": REPO_ROOT},
                }
            }
        }
        fd, path = tempfile.mkstemp(suffix=".json", prefix="judge_mcp_")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        return path
