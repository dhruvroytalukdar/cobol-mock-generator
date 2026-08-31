"""Locate ``COPY`` and ``EXEC SQL INCLUDE`` statements in COBOL source text.

Both forms are copybook inclusion and are handled identically downstream.  The
AST cannot see either (design plan section 1.3, Limitation 3: ``COPY`` produces
no node and ``EXEC SQL INCLUDE`` produces nothing at all), so this scan is
text-level by necessity -- but it runs over the lexer's mask, so ``COPY`` inside
a comment or a string literal is never matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .lexer import Kind, SourceLexer

# COPY name [OF|IN library] [REPLACING ...] .
_COPY = re.compile(
    r"\bCOPY\s+(?P<name>[A-Za-z0-9$#@_-]+)"
    r"(?:\s+(?:OF|IN)\s+(?P<lib>[A-Za-z0-9$#@_-]+))?"
    r"(?P<rest>.*?)"
    r"\.",
    re.IGNORECASE | re.DOTALL,
)

# INCLUDE name -- matched only inside an EXEC SQL block.
_INCLUDE = re.compile(r"\bINCLUDE\s+(?P<name>[A-Za-z0-9$#@_-]+)", re.IGNORECASE)


@dataclass
class CopyStatement:
    """One copybook-inclusion statement located in the source."""

    start: int              # offset of the C of COPY / the E of EXEC
    end: int                # offset just past the terminating period / END-EXEC
    name: str
    library: Optional[str]
    replacing: str          # raw REPLACING clause text ("" when absent)
    form: str               # "COPY" or "EXEC_SQL_INCLUDE"
    raw: str                # verbatim statement text


def scan_copy_statements(text: str, lexer: Optional[SourceLexer] = None) -> List[CopyStatement]:
    """Return every COPY / EXEC SQL INCLUDE in ``text``, in document order."""
    lx = lexer or SourceLexer(text)
    found: List[CopyStatement] = []

    # -- EXEC SQL INCLUDE: search within known EXEC SQL block spans ----------
    include_spans: List[tuple[int, int]] = []
    for blk in lx.exec_blocks:
        if blk.dialect != "SQL":
            continue
        m = _INCLUDE.search(blk.body)
        if not m:
            continue
        # Confirm INCLUDE is the statement verb, not a word inside another
        # clause: the body must start with EXEC SQL INCLUDE.
        head = blk.body.split()
        if len(head) < 3 or head[2].upper() != "INCLUDE":
            continue
        end = blk.end
        # Swallow a directly following period so the spliced copybook text is
        # not preceded by a stray terminator.
        if end < len(text) and text[end] == ".":
            end += 1
        found.append(
            CopyStatement(
                start=blk.start,
                end=end,
                name=m.group("name").upper(),
                library=None,
                replacing="",
                form="EXEC_SQL_INCLUDE",
                raw=text[blk.start : end],
            )
        )
        include_spans.append((blk.start, end))

    # -- COPY statements -----------------------------------------------------
    pos = 0
    while True:
        m = _COPY.search(text, pos)
        if not m:
            break
        start = m.start()
        # Must be live program text, and must not sit inside an EXEC block
        # (an INCLUDE handled above, or a literal mentioning COPY).
        if lx.kind_at(start) != Kind.CODE:
            pos = m.start() + 4
            continue
        if any(s <= start < e for s, e in include_spans):
            pos = m.start() + 4
            continue

        rest = m.group("rest") or ""
        replacing = ""
        if re.search(r"\bREPLACING\b", rest, re.IGNORECASE):
            replacing = rest[re.search(r"\bREPLACING\b", rest, re.IGNORECASE).end() :]

        found.append(
            CopyStatement(
                start=start,
                end=m.end(),
                name=m.group("name").upper(),
                library=(m.group("lib") or None),
                replacing=replacing.strip(),
                form="COPY",
                raw=m.group(0),
            )
        )
        pos = m.end()

    found.sort(key=lambda c: c.start)
    return found
