"""``COPY ... REPLACING`` substitution.

No program in the GenApp corpus uses ``REPLACING``, so this path is exercised
only by synthetic fixtures (design plan section 4.6 flags that as residual
risk).  It is implemented for generality and to keep the inliner honest about
COBOL macro semantics.

Three operand forms are supported:

``==pseudo text==``
    Token-sequence match, tolerant of differing whitespace runs and line breaks.
``literal`` (``'x'`` / ``"x"``)
    Exact literal match.
``identifier``
    Whole-word, case-insensitive.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

_PSEUDO = re.compile(r"==(?P<body>.*?)==", re.DOTALL)


@dataclass
class ReplacePair:
    pattern: str
    replacement: str
    mode: str  # "pseudo" | "literal" | "identifier"


def _split_operands(clause: str) -> List[str]:
    """Split a REPLACING clause into alternating from/to operands."""
    ops: List[str] = []
    i = 0
    n = len(clause)
    while i < n:
        ch = clause[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if clause.startswith("==", i):
            m = _PSEUDO.match(clause, i)
            if not m:
                break
            ops.append(m.group(0))
            i = m.end()
            continue
        if ch in ("'", '"'):
            j = clause.find(ch, i + 1)
            if j == -1:
                ops.append(clause[i:])
                break
            ops.append(clause[i : j + 1])
            i = j + 1
            continue
        if clause[i : i + 2].upper() == "BY" and (
            i + 2 >= n or not (clause[i + 2].isalnum() or clause[i + 2] in "-_")
        ):
            i += 2
            continue
        m = re.match(r"[A-Za-z0-9$#@_()-]+", clause[i:])
        if not m:
            i += 1
            continue
        ops.append(m.group(0))
        i += m.end()
    return ops


def parse_replacing(clause: str) -> List[ReplacePair]:
    """Parse a REPLACING clause body into ordered from/to pairs."""
    ops = _split_operands(clause)
    pairs: List[ReplacePair] = []
    for a, b in zip(ops[0::2], ops[1::2]):
        if a.startswith("=="):
            pairs.append(ReplacePair(a[2:-2], b[2:-2] if b.startswith("==") else b, "pseudo"))
        elif a[:1] in ("'", '"'):
            pairs.append(ReplacePair(a, b, "literal"))
        else:
            pairs.append(ReplacePair(a, b, "identifier"))
    return pairs


def _pseudo_regex(body: str) -> re.Pattern:
    """Match a pseudo-text token sequence with flexible whitespace between tokens."""
    tokens = body.split()
    if not tokens:
        return re.compile(r"(?!x)x")  # never matches
    return re.compile(r"\s+".join(re.escape(t) for t in tokens), re.IGNORECASE)


def apply_replacing(text: str, pairs: List[ReplacePair]) -> str:
    """Apply ``pairs`` left to right.

    Each pair scans forward past its own replacement so a replacement that
    contains the pattern cannot loop forever.
    """
    for pair in pairs:
        if pair.mode == "pseudo":
            rx = _pseudo_regex(pair.pattern)
        elif pair.mode == "literal":
            rx = re.compile(re.escape(pair.pattern))
        else:
            rx = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(pair.pattern)}(?![A-Za-z0-9_-])",
                            re.IGNORECASE)

        out: List[str] = []
        pos = 0
        while True:
            m = rx.search(text, pos)
            if not m:
                out.append(text[pos:])
                break
            out.append(text[pos : m.start()])
            out.append(pair.replacement)
            pos = m.end()
            if m.end() == m.start():  # zero-width guard
                if pos >= len(text):
                    break
                out.append(text[pos])
                pos += 1
        text = "".join(out)
    return text
