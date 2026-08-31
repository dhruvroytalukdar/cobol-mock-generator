"""Repair source defects that IBM's compiler tolerates but GnuCOBOL rejects.

Strictly limited to punctuation the COBOL standard already requires: nothing
here changes what a program computes, it only makes an existing declaration
well formed.  Every repair is reported as a diagnostic so it is visible rather
than silent.

Currently one repair is needed by the corpus: ``lgwebst5.cbl`` omits the period
after its ``PROGRAM-ID`` paragraph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from ..errors import Diagnostic, Severity
from ..linetools import LineIndex, is_comment_line

_PROGRAM_ID_LINE = re.compile(
    r"^(?P<head>\s*PROGRAM-ID\s*\.\s*)(?P<name>[A-Za-z0-9$#@_-]+)(?P<tail>\s*)$",
    re.IGNORECASE,
)


@dataclass
class RepairResult:
    text: str
    diagnostics: List[Diagnostic]


def repair(text: str) -> RepairResult:
    """Apply the minimal punctuation repairs GnuCOBOL requires."""
    index = LineIndex(text)
    lines = text.split("\n")
    diagnostics: List[Diagnostic] = []

    for i, raw in enumerate(lines):
        if is_comment_line(raw) or not raw.strip():
            continue
        code = raw[7:72] if len(raw) > 7 else ""
        m = _PROGRAM_ID_LINE.match(code)
        if not m:
            continue
        # The paragraph is unterminated; COBOL requires a period here.
        rebuilt = raw[:7] + m.group("head") + m.group("name") + "."
        lines[i] = rebuilt + raw[72:] if len(raw) > 72 else rebuilt
        diagnostics.append(
            Diagnostic(
                code="W-SYNTAX-REPAIR",
                message=(
                    f"PROGRAM-ID paragraph for {m.group('name')} was missing its "
                    "terminating period; added so the program compiles"
                ),
                severity=Severity.WARNING,
                line=i + 1,
            )
        )
        break  # only the first PROGRAM-ID matters

    return RepairResult("\n".join(lines), diagnostics)
