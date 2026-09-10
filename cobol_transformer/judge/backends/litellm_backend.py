"""LiteLLMBackend: the plug-and-play path.

``litellm.completion(model=..., messages=..., tools=...)`` normalizes
function-calling across 100+ providers (Anthropic, OpenAI, Groq, Bedrock,
OpenRouter, Ollama, ...), so swapping the underlying model is a
``--model <provider>/<name>`` string with no code change here. The judge's
own MCP tool server is bridged in via :mod:`mcp_bridge` since LiteLLM does not
manage MCP servers itself.

The relevant provider API key (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``,
``GROQ_API_KEY``, ...) must already be set in the environment -- LiteLLM picks
it up by convention from the ``--model`` prefix.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

import litellm

from .base import JudgeBackend, JudgeRunResult
from .mcp_bridge import MCPBridge

# ``python -m cobol_transformer...`` only resolves when cwd is the repo root
# (the package isn't pip-installed) -- set explicitly rather than relying on
# whatever cwd the spawning process happens to have.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_MAX_TURNS = 12


DEFAULT_TIMEOUT = 900  # seconds; matches ClaudeCLIBackend's default


class LiteLLMBackend(JudgeBackend):
    def __init__(
        self,
        model: str,
        reasoning_effort: Optional[str] = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_turns = max_turns
        # Unlike ClaudeCLIBackend's bounded subprocess, neither the provider
        # API call nor the MCP tool round-trip had any timeout at all -- a
        # provider stall or a hung tools_server.py subprocess would block
        # forever, and because that never raises, run_batch.py's per-case
        # exception isolation cannot catch it either.  Bounded here instead.
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
        try:
            return asyncio.run(
                self._run_async(
                    system_prompt, task_prompt, case_dir, output_dir, tools_enabled,
                    allowed_mcp_tools,
                )
            )
        except (asyncio.TimeoutError, TimeoutError):
            # A direct, single-case invocation of this backend must fail with
            # a clean JudgeRunResult like ClaudeCLIBackend's timeout path,
            # not an uncaught exception -- run_batch.py's own per-case
            # exception isolation is a second line of defense, not the only
            # one this backend should rely on.
            return JudgeRunResult(raw_output="", error=f"timed out after {self.timeout}s")

    async def _run_async(
        self,
        system_prompt: str,
        task_prompt: str,
        case_dir: Optional[str],
        output_dir: Optional[str],
        tools_enabled: bool,
        allowed_mcp_tools: Optional[List[str]] = None,
    ) -> JudgeRunResult:
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        ]
        transcript: List[Any] = list(messages)

        if not tools_enabled:
            resp = self._complete(messages, tools=None)
            content = resp.choices[0].message.content or ""
            transcript.append({"role": "assistant", "content": content})
            return JudgeRunResult(raw_output=content, transcript=transcript)

        if not (case_dir and output_dir):
            raise ValueError("tools_enabled requires case_dir and output_dir")

        final_text = ""
        async with MCPBridge(
            command=sys.executable,
            args=["-m", "cobol_transformer.judge.tools_server", case_dir, output_dir],
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        ) as bridge:
            tools = await asyncio.wait_for(
                bridge.list_tools_openai_schema(), timeout=self.timeout
            )
            if allowed_mcp_tools is not None:
                allowed_names = set(allowed_mcp_tools)
                tools = [t for t in tools if t["function"]["name"] in allowed_names]

            for _ in range(self.max_turns):
                resp = self._complete(messages, tools=tools)
                msg = resp.choices[0].message
                msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else dict(msg)
                messages.append(msg_dict)
                transcript.append(msg_dict)

                tool_calls = getattr(msg, "tool_calls", None)
                if not tool_calls:
                    final_text = msg.content or ""
                    break

                for call in tool_calls:
                    name = call.function.name
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result_text = await asyncio.wait_for(
                            bridge.call_tool(name, args), timeout=self.timeout
                        )
                    except (asyncio.TimeoutError, TimeoutError):
                        # str(asyncio.TimeoutError()) is "" -- the generic
                        # branch below would otherwise surface a message with
                        # nothing after the colon.
                        result_text = f"error calling {name}: timed out after {self.timeout}s"
                    except Exception as exc:  # noqa: BLE001 -- surfaced to the model, not raised
                        result_text = f"error calling {name}: {exc}"
                    tool_msg = {"role": "tool", "tool_call_id": call.id, "content": result_text}
                    messages.append(tool_msg)
                    transcript.append(tool_msg)
            else:
                final_text = "(max turns reached without a final answer)"

        return JudgeRunResult(raw_output=final_text, transcript=transcript)

    def _complete(self, messages: List[Dict[str, Any]], tools: Optional[List[dict]]):
        kwargs: Dict[str, Any] = {
            "model": self.model, "messages": messages, "timeout": self.timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        return litellm.completion(**kwargs)
