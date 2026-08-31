"""Pin AST nodes to real offsets in the canonical text by verbatim search.

AST line numbers drift from physical lines and carry no copybook provenance, so
they are never read.  Instead each classified node's ``Source Text`` -- which is
an exact substring of the submitted source -- is located by forward search from
a monotonically advancing cursor.  Processing nodes in document order means two
byte-identical statements (two identical ``EXEC CICS ABEND`` blocks, say) each
match their own occurrence instead of both collapsing onto the first.

Failure is always fail-closed: a node that cannot be located is skipped and
reported, never guessed at.  An unmocked statement is a visible compile error;
a mis-anchored splice would silently corrupt unrelated code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..ast_client.ast_model import AstDocument, AstNode
from ..errors import Diagnostic, Severity
from .node_classifier import Category, ClassifierRule, NodeClassifier


@dataclass
class ReplacementRange:
    """A located, classified span of the canonical text."""

    start: int
    end: int
    node: Optional[AstNode]
    category: Category
    rule_name: str
    is_statement: bool
    #: Set later by rewrite.terminator.
    had_trailing_period: bool = False
    #: ``end`` extended past a sentence-terminating period, when one belongs
    #: to this statement.  Equals ``end`` otherwise.
    term_end: int = 0
    source_text: str = ""

    def __post_init__(self) -> None:
        if self.term_end == 0:
            self.term_end = self.end


@dataclass
class AnchorResult:
    ranges: List[ReplacementRange] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    #: Number of nodes classified but not successfully anchored.
    skipped: int = 0


def _flexible_pattern(needle: str) -> re.Pattern:
    """A regex matching ``needle`` with any run of whitespace where it has one.

    Used only as a second attempt when the exact substring is absent, which can
    happen if the serializer reflows whitespace inside a construct.  Literal
    text between whitespace runs must still match exactly.
    """
    parts = [re.escape(p) for p in needle.split()]
    return re.compile(r"\s+".join(parts))


def anchor_nodes(
    text: str,
    document: AstDocument,
    classifier: Optional[NodeClassifier] = None,
) -> AnchorResult:
    """Locate every classified node of ``document`` inside ``text``."""
    cls = classifier or NodeClassifier()
    result = AnchorResult()
    cursor = 0

    for node in document.walk(prune=cls.is_pruned):
        rule: Optional[ClassifierRule] = cls.classify(node)
        if rule is None:
            continue
        needle = node.source_text
        if not needle:
            continue

        idx = text.find(needle, cursor)
        matched_len = len(needle)

        if idx == -1:
            # Whitespace-tolerant retry before giving up.
            m = _flexible_pattern(needle).search(text, cursor)
            if m:
                idx, matched_len = m.start(), m.end() - m.start()

        if idx == -1:
            before = text.find(needle, 0, cursor)
            code = "E-ANCHOR-OUT-OF-ORDER" if before != -1 else "E-ANCHOR-NOT-FOUND"
            msg = (
                f"{node.node_type} source text could not be located at or after "
                f"offset {cursor}"
            )
            if before != -1:
                msg += f" (found only earlier at {before}: document order violated)"
            result.diagnostics.append(
                Diagnostic(
                    code=code,
                    message=msg,
                    severity=Severity.ERROR,
                    detail={"node_type": node.node_type,
                            "snippet": needle[:120]},
                )
            )
            result.skipped += 1
            continue  # cursor deliberately not advanced

        result.ranges.append(
            ReplacementRange(
                start=idx,
                end=idx + matched_len,
                node=node,
                category=rule.category,
                rule_name=rule.name,
                is_statement=rule.is_statement,
                source_text=text[idx : idx + matched_len],
            )
        )
        cursor = idx + matched_len

    _assert_disjoint(result)
    return result


def _assert_disjoint(result: AnchorResult) -> None:
    """Validate the non-overlap invariant instead of assuming it."""
    ranges = result.ranges
    for a, b in zip(ranges, ranges[1:]):
        if a.end > b.start:
            result.diagnostics.append(
                Diagnostic(
                    code="E-ANCHOR-OVERLAP",
                    message=(
                        f"anchored ranges overlap: [{a.start},{a.end}) and "
                        f"[{b.start},{b.end}) - output would be corrupted"
                    ),
                    severity=Severity.ERROR,
                )
            )
