"""The judge agent's MCP tool server: read_file, get_failing_testcases,
get_coverage, write_file.

One process is started per (case_dir, output_dir) pair -- see
``backends/claude_cli.py`` and ``backends/mcp_bridge.py`` for how each
backend spawns it. Because it's scoped to a single already-prepared case
(see :mod:`prepare_case`), none of the tools take a directory/session
argument the way the earlier ``obs_vs_bug_v1.md`` tools did.

    python -m cobol_transformer.judge.tools_server <case_dir> <output_dir>
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

from mcp.server.mcpserver import MCPServer

_ALLOWED_READ_FILES = {"original.cbl", "modified.cbl", "intent.md"}


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def build_server(case_dir: str, output_dir: str) -> MCPServer:
    sandbox = os.path.join(case_dir, "sandbox")
    data_dir = os.path.join(case_dir, "_data")
    os.makedirs(output_dir, exist_ok=True)

    testcases = _load_json(os.path.join(data_dir, "testcases.json"))
    coverage = _load_json(os.path.join(data_dir, "coverage.json"))

    server = MCPServer("judge_tools")

    @server.tool()
    def read_file(path: str) -> str:
        """Read one of "original.cbl", "modified.cbl", or "intent.md"."""
        name = os.path.basename(path)
        if name not in _ALLOWED_READ_FILES:
            raise ValueError(
                f"path must be one of {sorted(_ALLOWED_READ_FILES)}, got {path!r}"
            )
        with open(os.path.join(sandbox, name), "r", encoding="utf-8") as fh:
            return fh.read()

    @server.tool()
    def get_failing_testcases() -> dict:
        """Every in-scope failing testcase: description, initial_values, and
        mismatches (variable/old_expected/actual_new). No arguments -- the
        set is fixed for this case."""
        return testcases

    @server.tool()
    def get_coverage(test_id: str) -> dict:
        """original_run/modified_run block coverage for one test_id: which
        paragraphs/branches (with their source line ranges) were exercised
        against the original program and against the modified program."""
        if test_id not in coverage:
            raise ValueError(
                f"unknown test_id {test_id!r}; call get_failing_testcases() for valid ids"
            )
        return coverage[test_id]

    @server.tool()
    def write_file(path: str, content: str) -> str:
        """Write the final answer (e.g. "verdicts.json") to this case's
        designated output location. path is a filename only, not a directory."""
        name = os.path.basename(path)
        target = os.path.join(output_dir, name)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        return f"wrote {name} ({len(content)} bytes) to the case output directory"

    return server


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 2:
        sys.stderr.write("usage: tools_server.py <case_dir> <output_dir>\n")
        return 2
    case_dir, output_dir = argv
    server = build_server(case_dir, output_dir)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
