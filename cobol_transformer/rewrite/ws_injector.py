"""Add the declarations a mocked program needs, and give LINKAGE real storage.

Two edits, both confined to the DATA DIVISION:

**Synthesised EIB fields.**  CICS supplies the EXEC Interface Block at run time;
the source declares none of it.  Any EIB field a program actually references is
emitted into WORKING-STORAGE under a banner, with the PICTURE CICS gives it.

**LINKAGE promotion.**  ``DFHCOMMAREA`` is declared in the LINKAGE SECTION and,
under CICS, addressed by the commarea the caller passed.  Run standalone there
is no caller, so those items have no storage and touching them would fault.
Commenting out the ``LINKAGE SECTION.`` header alone converts the entries that
follow into WORKING-STORAGE items -- their declarations, order, ``REDEFINES``
and group structure are untouched, they simply gain real backing storage.  This
is sound here because every program in the corpus places LINKAGE immediately
after WORKING-STORAGE and none has a ``PROCEDURE DIVISION USING`` clause (both
verified across all 31 programs).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..errors import Diagnostic, Severity
from ..inline.lexer import Kind, SourceLexer
from ..linetools import LineIndex, comment_out
from ..mocks.rules_eib import EIB_FIELDS

_WS_SECTION = re.compile(r"^\s*WORKING-STORAGE\s+SECTION\s*\.", re.IGNORECASE)
_LINKAGE_SECTION = re.compile(r"^\s*LINKAGE\s+SECTION\s*\.", re.IGNORECASE)
_LOCAL_SECTION = re.compile(r"^\s*LOCAL-STORAGE\s+SECTION\s*\.", re.IGNORECASE)
_PROC_DIVISION = re.compile(r"^\s*PROCEDURE\s+DIVISION\b", re.IGNORECASE)
_PROC_USING = re.compile(r"(PROCEDURE\s+DIVISION)\s+USING\b[^.]*", re.IGNORECASE)

BANNER = "      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<"
LINKAGE_NOTE = (
    "      * >>> LINKAGE SECTION promoted to WORKING-STORAGE by cobol_transformer:"
)
LINKAGE_NOTE2 = (
    "      * >>> no CICS caller supplies a commarea, so these items need storage."
)


@dataclass
class InjectionResult:
    text: str
    added_fields: List[str]
    diagnostics: List[Diagnostic]
    linkage_promoted: bool
    #: ``(0-based line index in the pre-injection text, lines added there)``.
    #: Callers use this to keep line numbers recorded earlier in the run
    #: pointing at the right lines of the final output.
    insertions: List[Tuple[int, int]] = None

    def shift(self, line_1based: int) -> int:
        """Map a 1-based pre-injection line number to the final text."""
        if not line_1based or not self.insertions:
            return line_1based
        delta = sum(n for pos, n in self.insertions if pos < line_1based)
        return line_1based + delta


def _find_section_lines(text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """0-based lines of WORKING-STORAGE, LINKAGE and PROCEDURE DIVISION."""
    lx = SourceLexer(text)
    index = LineIndex(text)
    ws = lk = pd = None
    for line in range(index.line_count):
        start = index.line_start(line)
        if lx.kind_at(start + 7) not in (Kind.CODE, Kind.IGNORED):
            continue
        raw = index.line_text(line)
        if raw[:6].strip() and not raw[6:7].strip():
            pass
        code = raw[7:72] if len(raw) > 7 else ""
        if not code.strip() or raw[6:7] in ("*", "/"):
            continue
        if ws is None and _WS_SECTION.match(code):
            ws = line
        elif lk is None and _LINKAGE_SECTION.match(code):
            lk = line
        elif pd is None and _PROC_DIVISION.match(code):
            pd = line
            break
    return ws, lk, pd


def inject(
    text: str,
    referenced_eib: List[str],
    promote_linkage: bool = True,
    extra_items: Optional[List[str]] = None,
) -> InjectionResult:
    """Insert synthesised fields and optionally promote the LINKAGE SECTION.

    ``extra_items`` carries pre-rendered declarations from the mock rules, such
    as the per-site loop counters that let browse and FETCH loops terminate.
    """
    diagnostics: List[Diagnostic] = []
    ws_line, lk_line, pd_line = _find_section_lines(text)
    lines = text.split("\n")
    promoted = False
    # Recorded in pre-injection coordinates, applied last so earlier indices
    # stay valid while the edits are being decided.
    insertions: List[Tuple[int, int]] = []

    if promote_linkage and lk_line is not None:
        if ws_line is None or ws_line > lk_line:
            diagnostics.append(
                Diagnostic(
                    code="W-LINKAGE-NOT-PROMOTED",
                    message=(
                        "LINKAGE SECTION does not follow WORKING-STORAGE; left as is, "
                        "so its items have no backing storage at run time"
                    ),
                    severity=Severity.WARNING,
                    line=lk_line + 1,
                )
            )
        else:
            lines[lk_line] = comment_out(lines[lk_line])
            promoted = True

    # A PROCEDURE DIVISION USING clause would demand arguments the standalone
    # program never receives; none exists in this corpus, but strip it if seen.
    if pd_line is not None and _PROC_USING.search(lines[pd_line]):
        lines[pd_line] = _PROC_USING.sub(r"\1", lines[pd_line])
        diagnostics.append(
            Diagnostic(
                code="W-PROC-USING-REMOVED",
                message="removed PROCEDURE DIVISION USING so the program runs standalone",
                severity=Severity.WARNING,
                line=pd_line + 1,
            )
        )

    added: List[str] = []
    extra_items = extra_items or []
    block: List[str] = []
    if referenced_eib or extra_items:
        block = [BANNER]
        for name, pic, value in EIB_FIELDS:
            if name not in referenced_eib:
                continue
            added.append(name)
            if name == "EIBCALEN":
                # A non-zero length is what tells a program a commarea
                # arrived, which is the path these programs expect.  The
                # value is the largest a PIC S9(4) field can hold.
                block.append(f"       01  {name:<12} PIC {pic} VALUE 9999.")
            elif value is None:
                block.append(f"       01  {name:<12} PIC {pic}.")
            else:
                block.append(f"       01  {name:<12} PIC {pic} VALUE {value}.")
        block.extend(extra_items)

    # Apply insertions from the bottom up so each index stays valid.
    pending: List[Tuple[int, List[str]]] = []
    if block:
        pending.append((pd_line if pd_line is not None else len(lines), block))
    if promoted:
        pending.append((lk_line, [LINKAGE_NOTE, LINKAGE_NOTE2]))

    for pos, payload in sorted(pending, key=lambda p: -p[0]):
        lines[pos:pos] = payload
        insertions.append((pos, len(payload)))

    return InjectionResult(
        text="\n".join(lines),
        added_fields=added,
        diagnostics=diagnostics,
        linkage_promoted=promoted,
        insertions=sorted(insertions),
    )
