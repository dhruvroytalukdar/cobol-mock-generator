"""Offset <-> line/column mapping and COBOL fixed-format column helpers.

Every offset in the pipeline is an index into one canonical ``expanded_text``
string whose line endings have already been normalised to ``\n``.  AST-reported
line numbers are never used (see design plan section 1.3, Limitation 1); this
module is the only source of line/column information.
"""
from __future__ import annotations

import bisect
from typing import List, Tuple

# COBOL fixed-format column layout, expressed as 0-based string indices.
SEQ_AREA = slice(0, 6)      # columns 1-6   sequence number area
INDICATOR_COL = 6           # column 7      indicator (*, /, -, D)
AREA_A_START = 7            # column 8      Area A
AREA_B_START = 11           # column 12     Area B
CODE_END = 72               # column 73     start of the identification area

DEFAULT_AREA_B_INDENT = AREA_B_START


class LineIndex:
    """Bisection index over newline offsets for one immutable text."""

    def __init__(self, text: str) -> None:
        self.text = text
        # starts[i] is the offset of the first character of 0-based line i.
        starts: List[int] = [0]
        pos = text.find("\n")
        while pos != -1:
            starts.append(pos + 1)
            pos = text.find("\n", pos + 1)
        self._starts = starts

    @property
    def line_count(self) -> int:
        return len(self._starts)

    def line_of(self, offset: int) -> int:
        """0-based physical line containing ``offset``."""
        if offset < 0:
            raise ValueError(f"negative offset {offset}")
        return bisect.bisect_right(self._starts, offset) - 1

    def line_col(self, offset: int) -> Tuple[int, int]:
        """1-based ``(line, column)`` for ``offset`` - the form used in reports."""
        line = self.line_of(offset)
        return line + 1, offset - self._starts[line] + 1

    def line_start(self, line: int) -> int:
        """Offset of the first character of 0-based ``line``."""
        return self._starts[line]

    def line_end(self, line: int) -> int:
        """Offset just past the last character of 0-based ``line``, excluding ``\n``."""
        if line + 1 < len(self._starts):
            return self._starts[line + 1] - 1
        return len(self.text)

    def line_text(self, line: int) -> str:
        """Text of 0-based ``line`` without its trailing newline."""
        return self.text[self.line_start(line) : self.line_end(line)]

    def lines_spanned(self, start: int, end: int) -> Tuple[int, int]:
        """0-based inclusive ``(first, last)`` physical lines touched by ``[start, end)``.

        An ``end`` sitting exactly on a line start belongs to the previous line:
        a range ending with the newline has not really entered the next line.
        """
        first = self.line_of(start)
        last = self.line_of(max(end - 1, start))
        return first, last


def indicator_of(line_text: str) -> str:
    """The indicator character (column 7) of ``line_text``, or a space if short."""
    if len(line_text) > INDICATOR_COL:
        return line_text[INDICATOR_COL]
    return " "


def is_comment_line(line_text: str) -> bool:
    """True for a fixed-format comment line (``*`` or ``/`` in column 7)."""
    return indicator_of(line_text) in ("*", "/")


def is_continuation_line(line_text: str) -> bool:
    """True for a fixed-format continuation line (``-`` in column 7)."""
    return indicator_of(line_text) == "-"


def is_blank_line(line_text: str) -> bool:
    return not line_text.strip()


def code_part(line_text: str) -> str:
    """Columns 8-72 of ``line_text`` - the part a COBOL compiler reads as code."""
    if is_comment_line(line_text):
        return ""
    return line_text[AREA_A_START:CODE_END]


def comment_out(line_text: str) -> str:
    """Return ``line_text`` with column 7 forced to ``*``.

    Columns 1-6 and 8 onward are preserved byte-for-byte so the original
    statement stays fully readable in the transformed file.  Lines shorter than
    the indicator column are padded with spaces first.
    """
    if len(line_text) <= INDICATOR_COL:
        line_text = line_text.ljust(INDICATOR_COL + 1)
        return line_text[:INDICATOR_COL] + "*"
    return line_text[:INDICATOR_COL] + "*" + line_text[INDICATOR_COL + 1 :]


def area_b_indent_of(line_text: str) -> int:
    """0-based indent of the first non-blank character in Area A/B of ``line_text``.

    Used to emit generated statements at the same column as the statement they
    mock.  Falls back to the standard Area B column for blank or short lines.
    """
    for i in range(AREA_A_START, min(len(line_text), CODE_END)):
        if line_text[i] != " ":
            return i
    return DEFAULT_AREA_B_INDENT
