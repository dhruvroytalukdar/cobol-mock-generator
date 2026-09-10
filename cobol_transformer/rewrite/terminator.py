"""Detect whether a mocked statement ends its COBOL sentence.

A COBOL period is a *sentence* terminator, not statement punctuation.  Inside an
``IF``/``PERFORM``/``EVALUATE`` body a period closes the enclosing scope, so
emitting a mock with a period where the original had none (or the reverse)
silently changes control flow.  The original's terminator is therefore detected
structurally and reproduced exactly, never inferred or standardised.
"""
from __future__ import annotations

from typing import List

from ..analysis.anchor import ReplacementRange
from ..linetools import is_comment_line


def scan_forward_period(text: str, end: int) -> int:
    """Offset just past a sentence-terminating period following ``end``, else ``end``.

    Only whitespace and whole comment lines may separate the statement from
    its period; any other token means the period (if any) belongs to a later
    statement.  A digit after the period would make it a decimal point, which
    cannot occur at a statement boundary but is rejected explicitly as a
    regression guard.
    """
    i = end
    n = len(text)
    while True:
        start = i
        while i < n and text[i] in " \t\r\n":
            i += 1
        line_start = text.rfind("\n", 0, i) + 1
        line_end = text.find("\n", line_start)
        if line_end == -1:
            line_end = n
        if is_comment_line(text[line_start:line_end]):
            i = line_end + 1 if line_end < n else n
        if i == start:
            break
    if i < n and text[i] == ".":
        nxt = text[i + 1] if i + 1 < n else ""
        if not nxt.isdigit():
            return i + 1
    return end


def annotate_terminators(text: str, ranges: List[ReplacementRange]) -> None:
    """Set ``had_trailing_period`` and ``term_end`` on each statement range.

    Sub-expression ranges (``DFHRESP(...)``) are left alone: they are replaced
    in place inside a live statement and have no terminator of their own.
    """
    for rng in ranges:
        if not rng.is_statement:
            rng.term_end = rng.end
            rng.had_trailing_period = False
            continue
        term_end = scan_forward_period(text, rng.end)
        rng.had_trailing_period = term_end > rng.end
        rng.term_end = term_end
