"""In-memory model of the Z Open Editor AST document.

Node shape (verified against the real serializer)::

    {"Node": "<TypeName>",
     "Source Text": "<verbatim substring>",
     "properties": {...},
     "Children": [...]}          # absent on leaves

Two facts about ``Source Text`` drive the code below:

* it is verbatim *except* that line endings come back as ``\\r\\n`` even when the
  submitted source used bare ``\\n``, so every needle is normalised before use;
* it is the only positional information that can be trusted -- the
  ``stmtStartLineNumber`` family drifts from true physical lines (design plan
  section 1.3, Limitation 1) and is never read.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional


def normalize_newlines(text: str) -> str:
    """Collapse CRLF/CR to LF - the single canonical line ending everywhere."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class AstNode:
    """One node of the concrete syntax tree."""

    node_type: str
    source_text: str                 # newline-normalised
    properties: Dict[str, Any]
    children: List["AstNode"]
    depth: int = 0

    @property
    def sql_or_cics(self) -> Optional[str]:
        v = self.properties.get("_SqlOrCics")
        return str(v).upper() if v else None

    @property
    def embedded_text(self) -> str:
        """Raw text between EXEC and END-EXEC, as the serializer reports it."""
        v = self.properties.get("embeddedLanguageObject")
        return normalize_newlines(str(v)) if v else ""

    def child_named(self, name: str) -> Optional["AstNode"]:
        for c in self.children:
            if c.node_type == name:
                return c
        return None

    def __repr__(self) -> str:  # pragma: no cover - display only
        head = self.source_text[:40].replace("\n", " ")
        return f"<AstNode {self.node_type} {head!r}>"


class AstDocument:
    """Wraps one parsed AST and provides a document-order walk."""

    def __init__(self, root: AstNode, file_path: str = "") -> None:
        self.root = root
        self.file_path = file_path

    @classmethod
    def from_json(cls, payload: Dict[str, Any], file_path: str = "") -> "AstDocument":
        """Build from either the server envelope or a bare AST object."""
        ast = payload.get("ast", payload) if isinstance(payload, dict) else payload
        return cls(_build(ast, 0), file_path or str(payload.get("filePath", "")))

    def walk(self, prune: Optional[callable] = None) -> Iterator[AstNode]:
        """Pre-order DFS over ``Children``.

        When ``prune(node)`` is true the node is yielded but its subtree is not
        descended -- used for ``ExecEndExec``, whose children are only a crude
        re-tokenisation of the same span.
        """
        stack: List[AstNode] = [self.root]
        while stack:
            node = stack.pop()
            yield node
            if prune is not None and prune(node):
                continue
            # Reversed so children are visited left to right.
            stack.extend(reversed(node.children))

    def count_nodes(self) -> int:
        return sum(1 for _ in self.walk())


def _build(raw: Dict[str, Any], depth: int) -> AstNode:
    children_raw = raw.get("Children") or []
    return AstNode(
        node_type=str(raw.get("Node", "")),
        source_text=normalize_newlines(str(raw.get("Source Text", ""))),
        properties=raw.get("properties") or {},
        children=[_build(c, depth + 1) for c in children_raw if isinstance(c, dict)],
        depth=depth,
    )
