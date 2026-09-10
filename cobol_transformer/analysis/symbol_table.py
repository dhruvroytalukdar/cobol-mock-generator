"""DATA DIVISION symbol table built from the canonical text.

Built by scanning text rather than the AST for two reasons: the same table is
needed on the fallback path (where no AST exists), and data-description entries
are strictly regular in fixed format, so a text scan is both simple and exact.
Comment lines are skipped by column-7 indicator; a data entry's own terminating
period is found by a quote-aware scan so a VALUE literal containing a period
(e.g. ``VALUE 'END OF FILE.'``) is never mistaken for the entry terminator.

Recorded per item: level, name, PICTURE, USAGE, REDEFINES, OCCURS, VALUE, the
owning section, and parent/child links reconstructed from level numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..inline.lexer import Kind, SourceLexer
from ..linetools import AREA_A_START, CODE_END, LineIndex, is_comment_line
from .pic_parser import PicCategory, PicInfo, parse_picture

_SECTION = re.compile(
    r"\b(WORKING-STORAGE|LINKAGE|LOCAL-STORAGE|FILE)\s+SECTION\s*\.", re.IGNORECASE
)
_PROCEDURE = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)
_DATA_DIVISION = re.compile(r"\bDATA\s+DIVISION\s*\.", re.IGNORECASE)

# level  name  ... .
_ENTRY = re.compile(
    r"^\s*(?P<level>0?[1-9]|[1-4][0-9]|66|77|88)\s+"
    r"(?P<name>[A-Za-z0-9$#@_-]+|FILLER)\b(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_PIC = re.compile(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(?P<pic>[^\s.]+(?:\([0-9]+\))?[^\s.]*)",
                  re.IGNORECASE)
_REDEFINES = re.compile(r"\bREDEFINES\s+([A-Za-z0-9$#@_-]+)", re.IGNORECASE)
_OCCURS = re.compile(r"\bOCCURS\s+(\d+)", re.IGNORECASE)
_USAGE = re.compile(
    r"\b(COMP-[0-9X]|COMP|COMPUTATIONAL(?:-[0-9X])?|BINARY|PACKED-DECIMAL|"
    r"POINTER|INDEX|DISPLAY)\b",
    re.IGNORECASE,
)
_VALUE = re.compile(r"\bVALUE\s+(?:IS\s+)?(?P<v>'[^']*'|\"[^\"]*\"|[^\s.]+)", re.IGNORECASE)


def _find_entry_terminator(s: str) -> int:
    """Index of the first period outside a quoted literal, or -1 if none.

    A period inside a ``VALUE`` literal (``VALUE 'END OF FILE.'``) is part of
    the literal's content, not the entry terminator -- splitting on it
    unconditionally would truncate the literal and desynchronize the rest of
    the entry's clauses.
    """
    in_string = False
    quote = ""
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_string:
            if ch == quote:
                if i + 1 < n and s[i + 1] == quote:
                    i += 2
                    continue
                in_string = False
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote = ch
            i += 1
            continue
        if ch == ".":
            return i
        i += 1
    return -1


@dataclass
class Symbol:
    name: str
    level: int
    section: str                       # WORKING-STORAGE | LINKAGE | ...
    pic_text: Optional[str] = None
    usage: Optional[str] = None
    redefines: Optional[str] = None
    occurs: int = 0
    value: Optional[str] = None
    parent: Optional[str] = None
    children: List[str] = field(default_factory=list)
    offset: int = 0                    # offset of the entry in the canonical text

    @property
    def is_group(self) -> bool:
        return self.pic_text is None and bool(self.children)

    @property
    def is_filler(self) -> bool:
        return self.name.upper() == "FILLER"

    @property
    def pic(self) -> PicInfo:
        return parse_picture(self.pic_text or "")

    @property
    def is_pointer(self) -> bool:
        return (self.usage or "").upper() == "POINTER"

    @property
    def is_condition(self) -> bool:
        return self.level == 88


class SymbolTable:
    """Case-insensitive symbol lookup with group hierarchy."""

    def __init__(self) -> None:
        self.symbols: Dict[str, Symbol] = {}     # upper name -> first definition
        self.all: List[Symbol] = []              # every entry, in document order
        self.sections: Dict[str, bool] = {}

    # -- lookup --------------------------------------------------------------

    def get(self, name: str) -> Optional[Symbol]:
        if not name:
            return None
        return self.symbols.get(name.upper())

    def __contains__(self, name: str) -> bool:
        return bool(name) and name.upper() in self.symbols

    def elementary_fields(self, name: str, _depth: int = 0) -> List[Symbol]:
        """Elementary (PIC-bearing) leaves under ``name``, in declaration order.

        A group's ``REDEFINES`` children are skipped: only the first
        interpretation of an overlapping area is populated, so a generated mock
        never writes the same bytes twice through two different views.
        """
        sym = self.get(name)
        if sym is None or _depth > 20:
            return []
        if sym.pic_text is not None:
            return [sym]
        out: List[Symbol] = []
        for child_name in sym.children:
            child = self.get(child_name)
            if child is None or child.is_condition or child.redefines:
                continue
            out.extend(self.elementary_fields(child_name, _depth + 1))
        return out

    def occurs_chain(self, name: str) -> List[Symbol]:
        """Every ``OCCURS``-bearing item in ``name``'s own-or-ancestor chain.

        Outermost first.  Covers both an item that repeats itself (``OCCURS``
        on an elementary field) and one nested under a repeating group -- both
        need a subscript to be referenced validly, and a field can need more
        than one when OCCURS tables are nested inside each other.
        """
        sym = self.get(name)
        if sym is None:
            return []
        chain: List[Symbol] = []
        node: Optional[Symbol] = sym
        depth = 0
        while node is not None and depth < 20:
            if node.occurs > 0:
                chain.append(node)
            node = self.get(node.parent) if node.parent else None
            depth += 1
        chain.reverse()
        return chain

    def subscript_for(self, name: str, index: int = 1) -> str:
        """The ``(i, i, ...)`` text ``name`` needs to be referenced validly.

        Empty string when ``name`` needs no subscript.  ``index`` is reused for
        every level -- a mock only needs to populate one deterministic element,
        not walk the whole table.
        """
        depth = len(self.occurs_chain(name))
        if depth == 0:
            return ""
        return "(" + ", ".join([str(index)] * depth) + ")"


def build_symbol_table(text: str, lexer: Optional[SourceLexer] = None) -> SymbolTable:
    """Scan the DATA DIVISION of ``text`` into a :class:`SymbolTable`.

    ``lexer`` is accepted (and reused by the caller elsewhere) but not needed
    here: comment lines are filtered directly by column-7 indicator, and the
    quote-aware entry-terminator scan below does its own literal masking.
    """
    index = LineIndex(text)
    table = SymbolTable()

    section = ""
    in_data = False
    # Stack of (level, name) for parent reconstruction.
    stack: List[tuple[int, str]] = []

    # Join each data entry's continuation lines: an entry runs until its period.
    pending = ""
    pending_offset = 0

    for line_no in range(index.line_count):
        ls = index.line_start(line_no)
        le = index.line_end(line_no)
        raw = text[ls:le]
        if is_comment_line(raw) or not raw.strip():
            continue
        code = raw[AREA_A_START:CODE_END] if len(raw) > AREA_A_START else ""
        if not code.strip():
            continue

        if _PROCEDURE.search(code):
            break
        if _DATA_DIVISION.search(code):
            in_data = True
            continue
        sm = _SECTION.search(code)
        if sm:
            section = sm.group(1).upper()
            table.sections[section] = True
            stack.clear()
            pending = ""
            continue
        if not in_data or not section:
            continue

        if not pending:
            pending_offset = ls + AREA_A_START
        pending += (" " if pending else "") + code.strip()
        if _find_entry_terminator(pending) == -1:
            continue  # entry continues on the next line

        # One or more complete entries may be present; process each.
        while True:
            term = _find_entry_terminator(pending)
            if term == -1:
                break
            head, pending = pending[:term], pending[term + 1:]
            pending = pending.strip()
            _consume_entry(head, section, stack, table, pending_offset)
        pending = ""

    return table


def _consume_entry(
    head: str,
    section: str,
    stack: List[tuple[int, str]],
    table: SymbolTable,
    offset: int,
) -> None:
    m = _ENTRY.match(head.strip())
    if not m:
        return
    level = int(m.group("level"))
    name = m.group("name")
    rest = m.group("rest") or ""

    if level == 88:
        return  # condition names carry no storage

    # Level 77 and 01 always restart the hierarchy.
    while stack and stack[-1][0] >= level:
        stack.pop()
    parent = stack[-1][1] if stack else None

    pic_m = _PIC.search(rest)
    usage_m = _USAGE.search(rest)
    red_m = _REDEFINES.search(rest)
    occ_m = _OCCURS.search(rest)
    val_m = _VALUE.search(rest)

    sym = Symbol(
        name=name,
        level=level,
        section=section,
        pic_text=pic_m.group("pic") if pic_m else None,
        usage=usage_m.group(1).upper() if usage_m else None,
        redefines=red_m.group(1) if red_m else None,
        occurs=int(occ_m.group(1)) if occ_m else 0,
        value=val_m.group("v") if val_m else None,
        parent=parent,
        offset=offset,
    )
    table.all.append(sym)
    key = name.upper()
    if key != "FILLER" and key not in table.symbols:
        table.symbols[key] = sym
    if parent and not sym.is_filler:
        psym = table.get(parent)
        if psym is not None:
            psym.children.append(name)
    elif parent and sym.is_filler:
        pass  # FILLER contributes storage but is never referenced by name

    if pic_m is None:  # a group item: it can own children
        stack.append((level, name))
