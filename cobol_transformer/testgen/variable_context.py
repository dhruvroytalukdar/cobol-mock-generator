"""Grounding facts about one transformed program, for prompts and validation.

Whatever picks initial values -- a model, or a person writing a test JSON by
hand -- needs to know which variables exist and what shape of value each will
accept.  Guessing produces literals that do not fit their PICTURE, which the
instrumenter would then have to reject.  This module answers that from the
program text itself.

The paragraph/section skeleton comes from ``pipeline``'s own scanner rather
than a second copy of the same regexes, so the structure reported here can
never drift from the structure the transformation pipeline sees.  Note that
this listing is *not* the coverage denominator: :mod:`cfg` computes that
independently from the AST.  The two are deliberately separate -- this one
informs the choice of inputs, that one scores what actually ran.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from ..analysis.pic_parser import PicCategory
from ..analysis.symbol_table import Symbol, SymbolTable, build_symbol_table
from ..inline.lexer import SourceLexer
from ..linetools import LineIndex
# Private, but deliberately shared: re-deriving the paragraph scan here would
# let this module's idea of program structure drift from the pipeline's.
from ..pipeline import _paragraph_map, _procedure_division_offset


@dataclass
class VariableFact:
    """One elementary field, described in the terms a test case needs."""

    name: str
    pic_text: str
    category: str
    length: int
    digits: int
    decimals: int
    signed: bool
    section: str
    level: int
    default_value: Optional[str] = None
    occurs: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["default_value"] is None:
            del d["default_value"]
        if not d["occurs"]:
            del d["occurs"]
        return d


@dataclass
class ProgramContext:
    program: str
    variables: List[VariableFact] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    symbols: Optional[SymbolTable] = None

    def variable(self, name: str) -> Optional[VariableFact]:
        upper = name.upper()
        for v in self.variables:
            if v.name.upper() == upper:
                return v
        return None

    def variables_json(self) -> str:
        return json.dumps([v.to_dict() for v in self.variables], indent=2)


def _is_settable(sym: Symbol, table: SymbolTable) -> bool:
    """True for a field a test case may sensibly assign a literal to.

    Group items, ``FILLER``, condition names and pointers are excluded: none of
    them takes a plain literal ``MOVE`` whose value a test author can reason
    about.  ``REDEFINES`` items are excluded because writing through one view
    would silently rewrite bytes another view owns.  A field that repeats
    itself or sits under a repeating ancestor (``OCCURS``, at any depth) is
    excluded too: an unqualified ``initial_values`` entry for it has no
    subscript, and the instrumenter has no single "the" element to move a
    literal into.
    """
    return (
        sym.pic_text is not None
        and not sym.is_filler
        and not sym.is_condition
        and not sym.is_pointer
        and not sym.redefines
        and sym.pic.category is not PicCategory.UNKNOWN
        and not table.occurs_chain(sym.name)
    )


def build_context(text: str, program: str) -> ProgramContext:
    """Describe ``text`` (one transformed program) for test-case generation."""
    lexer = SourceLexer(text)
    table = build_symbol_table(text, lexer)
    index = LineIndex(text)
    proc_offset = _procedure_division_offset(text, lexer)

    seen: Dict[str, bool] = {}
    facts: List[VariableFact] = []
    for sym in table.all:
        if not _is_settable(sym, table):
            continue
        key = sym.name.upper()
        if key in seen:
            continue          # first declaration wins, as in SymbolTable.get
        seen[key] = True
        pic = sym.pic
        facts.append(
            VariableFact(
                name=sym.name.upper(),
                pic_text=sym.pic_text or "",
                category=pic.category.value,
                length=pic.length,
                digits=pic.digits,
                decimals=pic.decimals,
                signed=pic.signed,
                section=sym.section,
                level=sym.level,
                default_value=sym.value,
                occurs=sym.occurs,
            )
        )

    paragraphs = [name for _, name in _paragraph_map(text, index, proc_offset, lexer)]
    return ProgramContext(
        program=program, variables=facts, paragraphs=paragraphs, symbols=table
    )
