"""DFHRESP substitution and synthesis of the EIB fields programs reference.

``DFHRESP(NORMAL)`` and friends appear inside ordinary conditions such as
``IF WS-RESP NOT = DFHRESP(NORMAL)``.  Commenting out that line would break the
``IF``, so this is the one construct replaced in place: the macro call becomes
the numeric condition value it stands for, and the surrounding statement is
untouched.

EXEC Interface Block fields (``EIBCALEN``, ``EIBTRNID``, ...) are supplied by
CICS at run time and are declared nowhere in the source, so any that a program
actually references are synthesised into WORKING-STORAGE.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from ..analysis.node_classifier import Category
from ..analysis.symbol_table import SymbolTable
from .rule_engine import MockResult, MockRule, RuleContext

_CONDITIONS_PATH = os.path.join(os.path.dirname(__file__), "cics_conditions.json")
_DFHRESP_CALL = re.compile(
    r"\bDFHRESP2?\s*\(\s*([A-Za-z0-9$#@_-]+)\s*\)", re.IGNORECASE
)

_conditions_cache: Optional[Dict[str, int]] = None


def condition_values() -> Dict[str, int]:
    global _conditions_cache
    if _conditions_cache is None:
        with open(_CONDITIONS_PATH, "r", encoding="utf-8") as fh:
            _conditions_cache = {k.upper(): int(v) for k, v in json.load(fh).items()}
    return _conditions_cache


class DfhrespRule(MockRule):
    """Replace ``DFHRESP(cond)`` with its numeric value, in place."""

    name = "cics_dfhresp"

    def matches(self, ctx: RuleContext) -> bool:
        return ctx.category is Category.DFHRESP

    def generate(self, ctx: RuleContext) -> MockResult:
        text = ctx.range.source_text
        table = condition_values()
        unknown: List[str] = []

        def sub(m: re.Match) -> str:
            name = m.group(1).upper()
            if name in table:
                return str(table[name])
            unknown.append(name)
            # An unknown condition is not NORMAL, so a non-zero sentinel keeps
            # "did this fail?" tests behaving as they did.
            return "9999"

        replaced = _DFHRESP_CALL.sub(sub, text)
        result = MockResult(inline_text=replaced)
        if unknown:
            from ..errors import Diagnostic, Severity

            result.diagnostics.append(
                Diagnostic(
                    code="W-DFHRESP-UNKNOWN",
                    message=f"unmapped CICS condition(s) {', '.join(unknown)}; used 9999",
                    severity=Severity.WARNING,
                )
            )
            result.confidence = "fallback"
        return result


# EIB fields, with the PICTURE CICS gives them.
EIB_FIELDS = [
    ("EIBTIME", "S9(7) COMP-3", "0"),
    ("EIBDATE", "S9(7) COMP-3", "0"),
    ("EIBTRNID", "X(4)", "'GENA'"),
    ("EIBTASKN", "S9(7) COMP-3", "1"),
    ("EIBTRMID", "X(4)", "'TRM1'"),
    ("EIBCPOSN", "S9(4) COMP", "0"),
    ("EIBCALEN", "S9(4) COMP", None),   # set from the commarea length below
    ("EIBAID", "X(1)", "SPACE"),
    ("EIBFN", "X(2)", "SPACE"),
    ("EIBRCODE", "X(6)", "SPACE"),
    ("EIBDS", "X(8)", "SPACE"),
    ("EIBREQID", "X(8)", "SPACE"),
    ("EIBRSRCE", "X(8)", "SPACE"),
    ("EIBSYNC", "X(1)", "SPACE"),
    ("EIBFREE", "X(1)", "SPACE"),
    ("EIBRECV", "X(1)", "SPACE"),
    ("EIBATT", "X(1)", "SPACE"),
    ("EIBEOC", "X(1)", "SPACE"),
    ("EIBFMH", "X(1)", "SPACE"),
    ("EIBCOMPL", "X(1)", "SPACE"),
    ("EIBSIG", "X(1)", "SPACE"),
    ("EIBCONF", "X(1)", "SPACE"),
    ("EIBERR", "X(1)", "SPACE"),
    ("EIBERRCD", "X(4)", "SPACE"),
    ("EIBSYNRB", "X(1)", "SPACE"),
    ("EIBNODAT", "X(1)", "SPACE"),
    ("EIBRESP", "S9(8) COMP", "0"),
    ("EIBRESP2", "S9(8) COMP", "0"),
    ("EIBRLDBK", "X(1)", "SPACE"),
]

#: ``(?<![...])``/``(?![...])`` instead of ``\b``: ``\b`` treats ``-`` as a
#: non-word character like whitespace, so plain ``\bEIB...\b`` would also
#: match the ``EIBCALEN`` inside an unrelated hyphenated name such as
#: ``WS-EIBCALEN-BACKUP``, wrongly concluding the real CICS pseudo-register
#: is referenced and synthesizing an unused declaration for it.
_IDENT = re.compile(r"(?<![A-Za-z0-9_-])(EIB[A-Z0-9]+)(?![A-Za-z0-9_-])",
                    re.IGNORECASE)


def referenced_eib_fields(text: str, symbols: SymbolTable) -> List[str]:
    """EIB names the program uses but does not declare."""
    known = {name for name, _, _ in EIB_FIELDS}
    used: List[str] = []
    for m in _IDENT.finditer(text):
        name = m.group(1).upper()
        if name in known and name not in symbols and name not in used:
            used.append(name)
    return used
