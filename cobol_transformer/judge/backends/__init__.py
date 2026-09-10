"""Swappable judge-agent runtimes behind one interface (:class:`JudgeBackend`).

* :class:`ClaudeCLIBackend` -- headless ``claude -p``, same pattern as
  ``testgen/generate_testcases.py``. Default for Haiku/low-effort runs.
* :class:`LiteLLMBackend` -- a small custom tool-call loop on
  ``litellm.completion``, bridged to the same MCP tool server via
  :mod:`mcp_bridge`. Swapping the underlying model/provider is a
  ``--model <provider>/<name>`` string, no code change.
"""
from .base import JudgeBackend, JudgeRunResult
from .claude_cli import ClaudeCLIBackend
from .litellm_backend import LiteLLMBackend

__all__ = ["JudgeBackend", "JudgeRunResult", "ClaudeCLIBackend", "LiteLLMBackend"]
