"""Lexer-driven detection, used when the AST backend cannot parse a file.

The Z Open Editor language server refuses to emit an AST when its *CICS
validator* objects to a command -- for example ``SEND TEXT ... WAIT`` without
``TERMINAL``, which several GenApp programs use.  Those are valid statements to
mock; the tool simply declines to describe them.

Detection here produces exactly the same ``ReplacementRange`` objects as the
AST path.  That is safe because the AST is *provably blind* inside an EXEC block
anyway (design plan section 1.3, Limitation 2: the body arrives as unparsed raw
text), so the AST contributes nothing beyond the span boundaries -- and those
boundaries were verified byte-identical to this scanner's on all 26 corpus files
where both paths run (see ``tests/unit/test_detector_parity.py``).
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..ast_client.ast_model import AstNode
from ..errors import Diagnostic
from ..inline.lexer import Kind, SourceLexer
from .anchor import AnchorResult, ReplacementRange, _assert_disjoint
from .node_classifier import Category

_DFHRESP = re.compile(r"\bDFHRESP2?\s*\(\s*([A-Za-z0-9$#@_-]+)\s*\)", re.IGNORECASE)

_CATEGORY_BY_DIALECT = {
    "CICS": Category.CICS,
    "SQL": Category.SQL,
    "UNKNOWN": Category.EXEC_UNKNOWN,
}


def _synthetic_node(kind: str, text: str, dialect: Optional[str], body: str) -> AstNode:
    """Build an AstNode-shaped record so downstream code is path-agnostic."""
    props = {"embeddedLanguageObject": body}
    if dialect:
        props["_SqlOrCics"] = dialect
    return AstNode(node_type=kind, source_text=text, properties=props, children=[])


def detect_by_text(text: str, lexer: Optional[SourceLexer] = None) -> AnchorResult:
    """Find every EXEC block and DFHRESP macro using only the lexical mask."""
    lx = lexer or SourceLexer(text)
    result = AnchorResult()

    for blk in lx.exec_blocks:
        category = _CATEGORY_BY_DIALECT.get(blk.dialect, Category.EXEC_UNKNOWN)
        # Strip the leading "Exec CICS"/"Exec SQL" so the body matches what the
        # AST's embeddedLanguageObject carries.
        body = re.sub(
            r"^\s*EXEC\s+(?:CICS|SQL)\s*", "", blk.body, count=1, flags=re.IGNORECASE
        )
        body = re.sub(r"\bEND-EXEC\s*$", "", body, flags=re.IGNORECASE)
        result.ranges.append(
            ReplacementRange(
                start=blk.start,
                end=blk.end,
                node=_synthetic_node("ExecEndExec", blk.text, blk.dialect, body),
                category=category,
                rule_name=f"text_exec_{blk.dialect.lower()}",
                is_statement=True,
                source_text=blk.text,
            )
        )

    for m in _DFHRESP.finditer(text):
        # Must be live code, and must not sit inside an EXEC block (a RESP
        # option is handled by the EXEC rule itself).
        if lx.kind_at(m.start()) != Kind.CODE:
            continue
        result.ranges.append(
            ReplacementRange(
                start=m.start(),
                end=m.end(),
                node=_synthetic_node("CicsDFHRESPmacro", m.group(0), None, ""),
                category=Category.DFHRESP,
                rule_name="text_dfhresp",
                is_statement=False,
                source_text=m.group(0),
            )
        )

    result.ranges.sort(key=lambda r: r.start)
    _assert_disjoint(result)
    return result
