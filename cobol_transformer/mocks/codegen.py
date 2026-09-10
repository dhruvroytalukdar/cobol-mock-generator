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

import re
from typing import List, Sequence

from ..linetools import CODE_END, DEFAULT_AREA_B_INDENT

MAX_COL = CODE_END          # generated text must end by column 72
CONT_EXTRA_INDENT = 4

_LITERAL_TOKEN = re.compile(r"'(?:[^']|'')*'")


def _tokenize(statement: str) -> List[str]:
    """Split on spaces, but keep each quoted literal as one indivisible token.

    Splitting a literal's interior on a space (the naive ``str.split(" ")``
    this replaces) would let the greedy line-packer below break a line in the
    middle of a string constant, with nothing marking the continuation --
    invalid COBOL (``continuation character expected``).  Treating the whole
    literal as one token keeps it intact whenever it fits on a line, and lets
    the "doesn't fit at all" case in ``_wrap`` be handled deliberately, with a
    real ``-`` continuation, instead of by accident.
    """
    tokens: List[str] = []
    pos = 0
    for m in _LITERAL_TOKEN.finditer(statement):
        if m.start() > pos:
            tokens.extend(statement[pos:m.start()].split())
        tokens.append(m.group(0))
        pos = m.end()
    if pos < len(statement):
        tokens.extend(statement[pos:].split())
    return tokens


def _is_literal(token: str) -> bool:
    return len(token) >= 2 and token[0] == token[-1] == "'"


def _split_literal(literal: str, first_width: int, cont_width: int) -> List[str]:
    """Split a ``'...'`` literal too long for one line into continuation pieces.

    Each piece already carries its own quote delimiters; concatenating the
    pieces' *values* (ignoring delimiters, in order) reconstructs the original
    content exactly, matching how COBOL concatenates a continued literal with
    no inserted whitespace.  A doubled quote (an escaped quote inside the
    literal) is never split across two pieces.

    Every *non-final* piece must fill its line to exactly ``width`` columns:
    COBOL takes the rest of a to-be-continued line literally, so a shorter
    piece leaves a gap that becomes spurious trailing spaces baked into the
    literal's own value.  A non-final piece opens (but never closes) its
    quote, so its budget is ``width - 1``, not ``width - 2``.
    """
    quote = literal[0]
    body = literal[1:-1]
    pieces: List[str] = []
    i = 0
    n = len(body)
    is_first = True
    while True:
        width = first_width if is_first else cont_width
        avail = max(width - 1, 1)  # every piece needs at least the open quote
        end = min(i + avail, n)
        if end < n and end > i and body[end - 1] == quote and body[end] == quote:
            end -= 1  # don't split an escaped quote pair
        if end >= n and (end - i) + 2 > width:
            # Closing here (chunk + open quote + close quote) would overflow
            # by exactly the close quote -- hold one character back so a
            # trivial extra piece can close the literal instead.
            end -= 1
        chunk = body[i:end]
        i = end
        is_last = i >= n
        pieces.append(quote + chunk + (quote if is_last else ""))
        is_first = False
        if is_last:
            return pieces


def _wrap(statement: str, indent: int) -> List[str]:
    """Lay one logical statement out over as many lines as it needs."""
    indent = max(indent, DEFAULT_AREA_B_INDENT)
    width = MAX_COL - indent
    words = _tokenize(statement)
    lines: List[str] = []
    cur = ""
    cont_indent = indent + CONT_EXTRA_INDENT
    cur_width = width

    def flush() -> None:
        nonlocal cur
        if cur:
            lines.append(" " * (indent if not lines else cont_indent) + cur)
            cur = ""

    for word in words:
        candidate = word if not cur else cur + " " + word
        if len(candidate) <= cur_width:
            cur = candidate
            continue

        flush()
        cur_width = MAX_COL - cont_indent
        if len(word) <= cur_width:
            cur = word
            continue

        # The token alone still doesn't fit on a fresh line.
        if _is_literal(word):
            # A continued (non-final) piece must fill its line to column 72
            # exactly -- COBOL takes the rest of a to-be-continued line
            # literally, so a piece sized any shorter leaves a gap that
            # becomes spurious trailing spaces baked into the literal's own
            # value.  The first piece's line may start at a shallower indent
            # than later ones, so it needs its own (wider) width.
            first_width = MAX_COL - (indent if not lines else cont_indent)
            pieces = _split_literal(word, first_width, cur_width)
            lines.append(" " * (indent if not lines else cont_indent) + pieces[0])
            for piece in pieces[1:]:
                # '-' in the indicator column (col 7) marks this physical line
                # as a continuation of the literal, resuming its value exactly
                # where the previous piece left off -- no word-break, no
                # inserted space.
                lines.append(" " * 6 + "-" + " " * max(cont_indent - 7, 1) + piece)
        else:
            # No sane way to split a single non-literal token (e.g. an
            # unusually long identifier); emit it as-is rather than corrupt it.
            lines.append(" " * (indent if not lines else cont_indent) + word)

    flush()
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
