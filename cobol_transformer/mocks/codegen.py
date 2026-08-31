"""Emit fixed-format COBOL statement text for generated mocks.

Two responsibilities that the rest of the mock layer relies on:

* **Column discipline.**  Generated text starts at the same Area B column as the
  statement it replaces and never runs past column 72, so it stays inside the
  compiler's code area.  Over-long statements are continued onto further lines
  at a deeper indent rather than truncated.
* **Terminator fidelity.**  The mock reproduces the original's sentence
  terminator exactly (see ``rewrite.terminator``): a period only when the
  original statement carried one, and then only on the final statement.
"""
from __future__ import annotations

from typing import List, Sequence

from ..linetools import CODE_END, DEFAULT_AREA_B_INDENT

MAX_COL = CODE_END          # generated text must end by column 72
CONT_EXTRA_INDENT = 4


def _wrap(statement: str, indent: int) -> List[str]:
    """Lay one logical statement out over as many lines as it needs."""
    indent = max(indent, DEFAULT_AREA_B_INDENT)
    width = MAX_COL - indent
    words = statement.split(" ")
    lines: List[str] = []
    cur = ""
    cont_indent = indent + CONT_EXTRA_INDENT
    cur_width = width

    for word in words:
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= cur_width:
            cur += " " + word
        else:
            lines.append(" " * (indent if not lines else cont_indent) + cur)
            cur = word
            cur_width = MAX_COL - cont_indent
    if cur:
        lines.append(" " * (indent if not lines else cont_indent) + cur)
    return lines


def render_statements(
    statements: Sequence[str],
    indent: int,
    terminate_with_period: bool,
) -> List[str]:
    """Render mock statements as fixed-format lines.

    ``terminate_with_period`` appends the sentence-ending period to the final
    statement only, restoring the original sentence boundary.  When it is False
    no period is emitted, so the mock continues the sentence into whatever
    statement originally followed.
    """
    stmts = [s.strip() for s in statements if s and s.strip()]
    if not stmts:
        # A construct that generates nothing still has to preserve a sentence
        # terminator, and CONTINUE is the no-op statement that can carry it.
        stmts = ["CONTINUE"]

    out: List[str] = []
    for i, stmt in enumerate(stmts):
        is_last = i == len(stmts) - 1
        text = stmt.rstrip(".")
        if is_last and terminate_with_period:
            text += "."
        out.extend(_wrap(text, indent))
    return out


def cobol_string_literal(value: str) -> str:
    """Quote ``value`` as a COBOL alphanumeric literal, doubling inner quotes."""
    return "'" + value.replace("'", "''") + "'"


def banner(text: str) -> str:
    """A full-width comment line carrying ``text``."""
    return "      * " + text[:65]
