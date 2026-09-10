"""Comment out the physical lines a mocked statement occupies.

The original statement is never deleted: every line it touches gets ``*`` forced
into the indicator column, and the generated mock is inserted directly below.
That keeps the transformed file a complete, reviewable record of what changed.

A line-purity check makes this fail-closed: if live code shares a line with the
statement, the range is rejected rather than commenting out code that is not
part of the construct.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..analysis.anchor import ReplacementRange
from ..errors import Diagnostic, Severity
from ..linetools import LineIndex, area_b_indent_of, comment_out, is_comment_line


@dataclass
class CommentBlock:
    """The commented rendering of one statement span."""

    first_line: int          # 0-based inclusive
    last_line: int           # 0-based inclusive
    lines: List[str]         # commented text, one entry per physical line
    indent: int              # Area B column the mock should be emitted at
    already_comment: List[bool]  # per line: was it already a comment pre-transform?


def purity_error(
    text: str, index: LineIndex, rng: ReplacementRange
) -> Optional[Diagnostic]:
    """Report a diagnostic when other live code shares the statement's lines."""
    first, last = index.lines_spanned(rng.start, rng.term_end)
    before = text[index.line_start(first) : rng.start]
    after = text[rng.term_end : index.line_end(last)]
    if before.strip() or after.strip():
        line_no, col = index.line_col(rng.start)
        return Diagnostic(
            code="E-COMMENT-LINE-NOT-PURE",
            message=(
                "statement shares a physical line with other code; commenting it "
                "would disable that code, so it was left untransformed"
            ),
            severity=Severity.ERROR,
            line=line_no,
            col=col,
            detail={
                "before": before.strip()[:60],
                "after": after.strip()[:60],
            },
        )
    return None


def build_comment_block(
    text: str, index: LineIndex, rng: ReplacementRange
) -> CommentBlock:
    """Render every physical line of ``rng`` as a COBOL comment line."""
    first, last = index.lines_spanned(rng.start, rng.term_end)
    lines: List[str] = []
    already_comment: List[bool] = []
    for line in range(first, last + 1):
        raw = index.line_text(line)
        # A blank line inside the statement is already inert; leaving it exactly
        # as it was keeps the output a faithful copy of the original.
        lines.append(raw if not raw.strip() else comment_out(raw))
        # A line that was already a comment (e.g. one option of a multi-line
        # EXEC CICS command disabled by the original author) must not be
        # reported as "commented by this tool" -- verify() would then wrongly
        # un-comment it on reconstruction, since re-applying comment_out() to
        # an already-commented line is a no-op and looks identical either way.
        already_comment.append(is_comment_line(raw))
    indent = area_b_indent_of(index.line_text(first))
    return CommentBlock(
        first_line=first, last_line=last, lines=lines, indent=indent,
        already_comment=already_comment,
    )
