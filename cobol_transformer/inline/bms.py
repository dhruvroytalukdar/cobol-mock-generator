"""Generate a COBOL symbolic map copybook from BMS macro source.

The GenApp corpus ships ``ssmap.bms`` (BMS assembler macros) but not the
``SSMAP`` COBOL copybook the menu programs ``COPY``.  On a real mainframe that
copybook is produced by assembling the map with ``TYPE=DSECT``; here it is
generated directly from the macro source using the documented symbolic-map
layout, so the copied field names and lengths match what the programs expect.

For each named ``DFHMDF`` field of each ``DFHMDI`` map, the standard layout is::

    02  <NAME>L  COMP PIC S9(4).      length / input data length
    02  <NAME>F       PIC X.          flag byte
    02  FILLER REDEFINES <NAME>F.
        03 <NAME>A    PIC X.          attribute byte
    02  <NAME>I       PIC X(n).       input value

with a parallel ``...O`` output view redefining the input structure.  A
``TIOAPFX=YES`` map carries a 12-byte prefix ahead of the first field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# A BMS statement is: [LABEL] MACRO OPERANDS, continued when column 72 is
# non-blank.  Labels start in column 1.
_STMT = re.compile(r"^(?P<label>[A-Z0-9$#@]*)\s+(?P<macro>DFHMSD|DFHMDI|DFHMDF)\s*(?P<ops>.*)$")
_CONT_COL = 71  # 0-based index of column 72


@dataclass
class BmsField:
    name: str
    length: int


@dataclass
class BmsMap:
    name: str
    fields: List[BmsField] = field(default_factory=list)


def _logical_statements(text: str) -> List[str]:
    """Join BMS continuation lines into logical statements.

    A statement continues when column 72 holds a non-blank character; the
    continuation line's operands resume at column 16.
    """
    out: List[str] = []
    buf: Optional[str] = None
    for raw in text.splitlines():
        if raw.startswith("*"):
            continue
        if not raw.strip():
            continue
        continued = len(raw) > _CONT_COL and raw[_CONT_COL] != " "
        body = raw[:_CONT_COL] if continued else raw
        if buf is None:
            buf = body.rstrip()
        else:
            # Continuation operands conventionally begin in column 16.
            buf += body[15:].rstrip() if len(body) > 15 else ""
        if not continued:
            out.append(buf)
            buf = None
    if buf is not None:
        out.append(buf)
    return out


def _operand(ops: str, key: str) -> Optional[str]:
    """Value of ``KEY=...`` in a BMS operand list, honouring parenthesised values."""
    m = re.search(rf"\b{key}=", ops)
    if not m:
        return None
    i = m.end()
    if i < len(ops) and ops[i] == "(":
        depth = 0
        for j in range(i, len(ops)):
            if ops[j] == "(":
                depth += 1
            elif ops[j] == ")":
                depth -= 1
                if depth == 0:
                    return ops[i : j + 1]
        return ops[i:]
    if i < len(ops) and ops[i] == "'":
        j = ops.find("'", i + 1)
        return ops[i : j + 1] if j != -1 else ops[i:]
    m2 = re.match(r"[^,]*", ops[i:])
    return m2.group(0) if m2 else None


def parse_bms(text: str) -> tuple[List[BmsMap], bool]:
    """Parse BMS source into maps of named fields; also report ``TIOAPFX=YES``."""
    maps: List[BmsMap] = []
    current: Optional[BmsMap] = None
    tioapfx = False

    for stmt in _logical_statements(text):
        m = _STMT.match(stmt)
        if not m:
            continue
        label = m.group("label").strip()
        macro = m.group("macro")
        ops = m.group("ops")

        if macro == "DFHMSD":
            if (_operand(ops, "TIOAPFX") or "").upper() == "YES":
                tioapfx = True
        elif macro == "DFHMDI":
            current = BmsMap(name=label)
            maps.append(current)
        elif macro == "DFHMDF":
            if not label or current is None:
                continue  # unnamed literal field: no symbolic-map entry
            raw_len = _operand(ops, "LENGTH")
            try:
                length = int((raw_len or "0").strip())
            except ValueError:
                length = 0
            if length <= 0:
                # LENGTH= is optional: BMS derives an unspecified length from
                # the field's own INITIAL text.  Without this fallback the
                # field is silently dropped from the generated symbolic map,
                # and any program referencing it by name fails to compile.
                raw_init = _operand(ops, "INITIAL")
                if raw_init and raw_init.startswith("'") and raw_init.endswith("'"):
                    length = len(raw_init[1:-1])
            if length > 0:
                current.fields.append(BmsField(name=label, length=length))
    return maps, tioapfx


def generate_symbolic_map(text: str) -> str:
    """Render BMS source as a fixed-format COBOL symbolic map copybook."""
    maps, tioapfx = parse_bms(text)
    lines: List[str] = [
        "      *****************************************************************",
        "      * SYMBOLIC MAP generated from BMS source by cobol_transformer.  *",
        "      * Layout follows the standard DFHMSD TYPE=DSECT expansion.      *",
        "      *****************************************************************",
    ]
    prefix = 12 if tioapfx else 0

    for mp in maps:
        if not mp.fields:
            continue
        lines.append(f"       01  {mp.name}I.")
        if prefix:
            lines.append(f"           02  FILLER PIC X({prefix}).")
        for f in mp.fields:
            lines.append(f"           02  {f.name}L    COMP PIC S9(4).")
            lines.append(f"           02  {f.name}F    PIC X.")
            lines.append(f"           02  FILLER REDEFINES {f.name}F.")
            lines.append(f"               03  {f.name}A    PIC X.")
            lines.append(f"           02  {f.name}I    PIC X({f.length}).")
        lines.append(f"       01  {mp.name}O REDEFINES {mp.name}I.")
        if prefix:
            lines.append(f"           02  FILLER PIC X({prefix}).")
        for f in mp.fields:
            # The 3 filler bytes cover the L (2 bytes) and F/A (1 byte) fields.
            lines.append("           02  FILLER PIC X(3).")
            lines.append(f"           02  {f.name}O    PIC X({f.length}).")
    return "\n".join(lines) + "\n"
