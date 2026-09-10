"""A minimal async MCP client wrapper, used only by :class:`LiteLLMBackend`.

The ``claude`` CLI manages MCP servers natively via ``--mcp-config``; a
LiteLLM-driven loop has no such built-in support, so this bridges the same
``tools_server.py`` process into the OpenAI-style function-calling schema
LiteLLM (and therefore every provider it fronts) expects.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class MCPBridge:
    def __init__(self, command: str, args: List[str], env: Optional[Dict[str, str]] = None):
        self._command = command
        self._args = args
        self._env = env
        self._stack: Optional[AsyncExitStack] = None
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "MCPBridge":
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=self._command, args=self._args, env=self._env)
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def list_tools_openai_schema(self) -> List[dict]:
        assert self.session is not None
        result = await self.session.list_tools()
        schemas = []
        for tool in result.tools:
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                },
            })
        return schemas

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        assert self.session is not None
        result = await self.session.call_tool(name, arguments)
        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                parts.append(text)
        if parts:
            return "\n".join(parts)
        try:
            return json.dumps(result.model_dump())
        except Exception:  # noqa: BLE001 -- last-resort stringification for scoring/debugging
            return str(result)
