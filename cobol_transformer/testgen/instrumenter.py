"""Insertion-only instrumentation of a transformed program.

Unlike the mock rewriter, which *replaces* statements and therefore has to
preserve each one's sentence-terminating period, this module only ever inserts
brand-new statements at a boundary.  It never edits an existing statement, so
``rewrite.terminator``'s scope tracking is not needed here.

That does **not** make periods a non-issue, and the difference is the single
sharpest edge in this file.  A probe inserted into a branch body must *not*
carry its own period::

    IF EIBCALEN > 0            IF EIBCALEN > 0
       GO TO A-GAIN.    -->       DISPLAY 'TC:COV:IF-0001-THEN'
                                  GO TO A-GAIN.

A period after the ``DISPLAY`` would close the IF sentence and leave ``GO TO
A-GAIN.`` running unconditionally -- a silent, compiling change of behaviour.
Branch probes and the pre-``GOBACK`` ``PERFORM`` therefore join the surrounding
sentence and carry no period; only a probe that opens a paragraph body, where a
fresh sentence is always legal, gets one.  ``Block.probe_period`` records which
case each block is.

Insertion preserves columns exactly.  Splicing at offset ``o`` emits a newline,
the generated lines, then a pad of ``o - line_start`` spaces, so whatever
followed ``o`` on that line resumes at the very column it started in.  The same
mechanism therefore handles a probe going in at the start of a line and one
going in mid-line, without a special case for either.

Two modes:

* ``oracle``   -- initial values plus a ``TC:DUMP:`` of every checked variable.
  Its output is the ground truth; nothing here ever invents an expected value.
* ``checked``  -- initial values, coverage probes, and a ``TC:CHK:`` comparison
  against the frozen expected values.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..analysis.pic_parser import PicInfo
from ..analysis.symbol_table import SymbolTable
from ..errors import Diagnostic, Severity, TransformError
from ..inline.lexer import Kind, SourceLexer
from ..linetools import AREA_A_START, LineIndex
from ..pipeline import _procedure_division_offset
from .cfg import Block, CoverageManifest
from .literal_format import (
    LiteralError, MAX_CHECKABLE_LENGTH, cobol_string_literal,
    pic_info_to_condition_literal, pic_info_to_move_literal,
    render_harness_statement, unsupported_reason,
)

INIT_PARAGRAPH = "ZZ-TESTCASE-INIT"
DUMP_PARAGRAPH = "ZZ-TESTCASE-DUMP"
CHECK_PARAGRAPH = "ZZ-TESTCASE-CHECK"
EOF_PARAGRAPH = "ZZ-TESTCASE-EOF"

#: Statements that end the run.  A ``PERFORM`` of the harness paragraph is
#: inserted immediately before each of them.
#: ``\b`` alone is not enough here: COBOL identifiers use ``-`` freely, and
#: ``\b`` treats it as a non-word character the same as whitespace, so plain
#: ``\bGOBACK\b`` would also match inside e.g. ``WS-GOBACK-FLAG``.  The
#: negative look-around instead excludes ``-`` (and the other identifier
#: characters) on both sides, matching only a genuine standalone token.
_NOT_IDENT_CHAR = r"[A-Za-z0-9_-]"
_EXIT_STATEMENT = re.compile(
    rf"(?<!{_NOT_IDENT_CHAR})GOBACK(?!{_NOT_IDENT_CHAR})"
    rf"|(?<!{_NOT_IDENT_CHAR})STOP\s+RUN(?!{_NOT_IDENT_CHAR})"
    rf"|(?<!{_NOT_IDENT_CHAR})EXIT\s+PROGRAM(?!{_NOT_IDENT_CHAR})",
    re.IGNORECASE,
)
_PROC_DIVISION = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)

BODY_INDENT = 11


class InstrumentError(TransformError):
    """A test case cannot be instrumented as written."""


@dataclass
class TestCase:
    """One test case, in the schema written to ``testsuites/<program>/testN.json``."""

    test_id: str
    program: str
    description: str = ""
    initial_values: Dict[str, str] = field(default_factory=dict)
    variables_to_check: List[str] = field(default_factory=list)
    expected_values: Optional[Dict[str, str]] = None
    generated_by: str = ""
    generated_at: str = ""
    oracle_source: str = ""
    path: str = ""

    @property
    def is_frozen(self) -> bool:
        """True once an oracle run has genuinely supplied the expected values.

        A case that checks no variables is frozen by definition: it asserts
        nothing about values and exists only to drive coverage, so there is
        nothing for the oracle to supply.  Otherwise, ``expected_values``
        alone is not proof of a real blessing: only a genuine ``bless()``
        run (oracle_runner.py) sets ``oracle_source``, so a case that has
        values but no oracle source got them from somewhere else -- a model
        ignoring the schema, or a hand-authoring mistake -- and must not be
        trusted as ground truth just because the field happens to be filled
        in.
        """
        if not self.variables_to_check:
            return True
        return self.expected_values is not None and bool(self.oracle_source)

    @classmethod
    def load(cls, path: str) -> "TestCase":
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return cls(
            test_id=raw.get("test_id") or os.path.splitext(os.path.basename(path))[0],
            program=raw.get("program", ""),
            description=raw.get("description", ""),
            initial_values=dict(raw.get("initial_values") or {}),
            variables_to_check=list(raw.get("variables_to_check") or []),
            expected_values=(dict(raw["expected_values"])
                             if raw.get("expected_values") else None),
            generated_by=raw.get("generated_by", ""),
            generated_at=raw.get("generated_at", ""),
            oracle_source=raw.get("oracle_source", ""),
            path=path,
        )

    def to_dict(self) -> dict:
        d = {
            "test_id": self.test_id,
            "program": self.program,
            "description": self.description,
            "initial_values": self.initial_values,
            "variables_to_check": self.variables_to_check,
        }
        if self.expected_values is not None:
            d["expected_values"] = self.expected_values
        for key in ("generated_by", "generated_at", "oracle_source"):
            if getattr(self, key):
                d[key] = getattr(self, key)
        return d

    def write(self, path: Optional[str] = None) -> str:
        target = path or self.path
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.to_dict(), fh, indent=2)
            fh.write("\n")
        return target


@dataclass
class InstrumentResult:
    text: str
    mode: str
    test_id: str
    program: str
    #: Block IDs actually probed -- stage 5 reads this instead of re-deriving
    #: what was instrumented from the generated source.
    blocks_instrumented: List[str] = field(default_factory=list)
    variables_instrumented: List[str] = field(default_factory=list)
    variables_skipped: Dict[str, str] = field(default_factory=dict)
    exit_points: int = 0
    diagnostics: List[Diagnostic] = field(default_factory=list)

    def manifest_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "program": self.program,
            "mode": self.mode,
            "blocks_instrumented": self.blocks_instrumented,
            "variables_instrumented": self.variables_instrumented,
            "variables_skipped": self.variables_skipped,
            "exit_points": self.exit_points,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }

    def write(self, source_path: str, manifest_path: Optional[str] = None) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(source_path)), exist_ok=True)
        with open(source_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(self.text)
        target = manifest_path or os.path.splitext(source_path)[0] + ".manifest.json"
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.manifest_dict(), fh, indent=2)
            fh.write("\n")
        return source_path


# -- splicing ---------------------------------------------------------------

def _splice(text: str, insertions: Sequence[Tuple[int, List[str]]]) -> str:
    """Apply ``(offset, lines)`` insertions, preserving every original column.

    Applied in descending offset order so that earlier offsets stay valid, the
    same discipline ``rewrite.ws_injector`` uses.  Each insertion re-indents the
    remainder of its line to the column it already occupied, so splicing
    mid-line never shifts code sideways.
    """
    index = LineIndex(text)
    grouped: Dict[int, List[str]] = {}
    for offset, lines in insertions:
        grouped.setdefault(offset, []).extend(lines)

    out = text
    for offset in sorted(grouped, reverse=True):
        lines = grouped[offset]
        if not lines:
            continue
        line = index.line_of(offset)
        col = offset - index.line_start(line)
        # Re-indent the remainder to the column it already held -- unless
        # nothing but blanks follows, in which case the pad would only leave
        # trailing whitespace behind.
        tail_is_blank = not text[offset:index.line_end(line)].strip()
        payload = "\n" + "\n".join(lines) + ("\n" if tail_is_blank else "\n" + " " * col)
        out = out[:offset] + payload + out[offset:]
    return out


def _comment(text: str) -> str:
    return "      * " + text[:63]


def _paragraph_header(name: str) -> str:
    return " " * AREA_A_START + name + "."


# -- locating the insertion points -----------------------------------------

def _procedure_body_offset(text: str, lexer: SourceLexer) -> int:
    """Offset just past the period that ends the PROCEDURE DIVISION header."""
    start = _procedure_division_offset(text, lexer)
    if start >= len(text):
        raise InstrumentError("no PROCEDURE DIVISION found in the program")
    dot = text.find(".", start)
    if dot == -1:
        raise InstrumentError("PROCEDURE DIVISION header is not terminated")
    return dot + 1


def _exit_offsets(text: str, lexer: SourceLexer, from_offset: int) -> List[int]:
    """Offsets of every run-ending statement in real code, in document order."""
    out: List[int] = []
    for m in _EXIT_STATEMENT.finditer(text, from_offset):
        if lexer.kind_at(m.start()) is Kind.CODE:
            out.append(m.start())
    return out


# -- statement generation ---------------------------------------------------

def _pic_of(symbols: SymbolTable, name: str) -> Optional[PicInfo]:
    sym = symbols.get(name)
    if sym is None:
        return None
    return sym.pic if sym.pic_text else None


def _init_statements(
    testcase: TestCase, symbols: SymbolTable
) -> Tuple[List[str], List[Diagnostic]]:
    """``MOVE <literal> TO <VAR>.`` for each initial value, or a hard failure.

    An initial value that does not fit its field is not something to work
    around: the test case says something the program cannot express, so it is
    reported rather than silently dropped or truncated.
    """
    lines: List[str] = []
    problems: List[str] = []
    diagnostics: List[Diagnostic] = []
    for name, value in testcase.initial_values.items():
        sym = symbols.get(name)
        if sym is None:
            problems.append(f"{name}: no such variable in this program")
            continue
        if sym.is_condition:
            problems.append(f"{name}: is a condition name, not a storage field")
            continue
        try:
            literal = pic_info_to_move_literal(_pic_of(symbols, name), str(value))
        except LiteralError as exc:
            problems.append(f"{name}: {exc}")
            continue
        lines.extend(
            render_harness_statement(
                ["MOVE", literal, "TO", sym.name.upper()], BODY_INDENT, period=True
            )
        )
    if problems:
        raise InstrumentError(
            f"{testcase.test_id}: invalid initial values -- "
            + "; ".join(problems)
        )
    if not lines:
        # A paragraph must not be empty; CONTINUE is the no-op that fills it.
        lines = render_harness_statement(["CONTINUE"], BODY_INDENT, period=True)
    return lines, diagnostics


def _dump_statements(names: Sequence[str]) -> List[str]:
    lines: List[str] = []
    for name in names:
        lines.extend(
            render_harness_statement(
                ["DISPLAY", cobol_string_literal(f"TC:DUMP:{name}="), name],
                BODY_INDENT, period=True,
            )
        )
    return lines


def _check_statements(
    names: Sequence[str], expected: Dict[str, str], symbols: SymbolTable
) -> Tuple[List[str], List[str], Dict[str, str]]:
    """``IF``/``ELSE`` comparisons against the frozen expected values.

    Returns the lines, the variables actually compared, and the ones skipped
    with the reason why -- a value the COBOL side cannot express as a literal
    is reported honestly instead of being asserted with a wrong literal.
    """
    lines: List[str] = []
    done: List[str] = []
    skipped: Dict[str, str] = {}
    for name in names:
        if name not in expected:
            skipped[name] = "no expected value was frozen for this variable"
            continue
        value = expected[name]
        pic = _pic_of(symbols, name)
        reason = unsupported_reason(pic, value)
        if reason is not None:
            skipped[name] = reason
            continue
        literal = pic_info_to_condition_literal(pic, value)

        def report(flag: str) -> List[str]:
            return render_harness_statement(
                ["DISPLAY",
                 cobol_string_literal(f"TC:CHK:{name}:MATCH={flag}:ACTUAL="),
                 name],
                BODY_INDENT + 4,
            )

        lines.extend(render_harness_statement(["IF", name, "=", literal], BODY_INDENT))
        lines.extend(report("Y"))
        lines.extend(render_harness_statement(["ELSE"], BODY_INDENT))
        lines.extend(report("N"))
        lines.extend(render_harness_statement(["END-IF"], BODY_INDENT, period=True))
        done.append(name)
    if not lines:
        lines = render_harness_statement(["CONTINUE"], BODY_INDENT, period=True)
    return lines, done, skipped


# -- the instrumenter itself ------------------------------------------------

def instrument(
    text: str,
    testcase: TestCase,
    symbols: SymbolTable,
    mode: str,
    manifest: Optional[CoverageManifest] = None,
) -> InstrumentResult:
    """Return ``text`` instrumented for ``mode`` (``oracle`` or ``checked``)."""
    if mode not in ("oracle", "checked"):
        raise InstrumentError(f"unknown instrumentation mode {mode!r}")
    if mode == "checked" and testcase.variables_to_check and (
        testcase.expected_values is None
    ):
        raise InstrumentError(
            f"{testcase.test_id}: has no expected_values; run the oracle first"
        )

    result = InstrumentResult(text="", mode=mode, test_id=testcase.test_id,
                              program=testcase.program)
    lexer = SourceLexer(text)
    body_offset = _procedure_body_offset(text, lexer)
    insertions: List[Tuple[int, List[str]]] = []

    # -- 1. initial values, as the program's first paragraph ---------------
    # It is placed before the original first paragraph/section header and
    # simply falls through into it, so no PERFORM is needed and the original
    # entry path is untouched.  GnuCOBOL accepts a paragraph ahead of the first
    # SECTION header; this was compiled and run before being relied on.
    init_lines, diags = _init_statements(testcase, symbols)
    result.diagnostics.extend(diags)
    insertions.append((
        body_offset,
        ["", _comment(">>> TOOL-GENERATED TEST CASE INIT <<<"),
         _paragraph_header(INIT_PARAGRAPH)] + init_lines + [""],
    ))

    # -- 2. coverage probes (checked mode only) ----------------------------
    trailer_paragraph = DUMP_PARAGRAPH if mode == "oracle" else CHECK_PARAGRAPH
    if mode == "checked" and manifest is not None:
        for block in manifest.blocks:
            if block.probe_offset <= 0:
                continue
            insertions.append((
                block.probe_offset,
                render_harness_statement(
                    ["DISPLAY", cobol_string_literal(f"TC:COV:{block.id}")],
                    BODY_INDENT, period=block.probe_period,
                ),
            ))
            result.blocks_instrumented.append(block.id)

    # -- 3. report at every exit point -------------------------------------
    exits = _exit_offsets(text, lexer, body_offset)
    for offset in exits:
        insertions.append((
            offset,
            render_harness_statement(["PERFORM", trailer_paragraph], BODY_INDENT),
        ))
    result.exit_points = len(exits)
    if not exits:
        result.diagnostics.append(
            Diagnostic(
                code="W-TESTGEN-NO-EXIT",
                message=(
                    "no GOBACK/STOP RUN/EXIT PROGRAM found; results will be "
                    f"reported only by fall-through into {EOF_PARAGRAPH}"
                ),
                severity=Severity.WARNING,
            )
        )

    # -- 4. trailer --------------------------------------------------------
    if mode == "oracle":
        body = _dump_statements(testcase.variables_to_check)
        missing = [n for n in testcase.variables_to_check if symbols.get(n) is None]
        if missing:
            raise InstrumentError(
                f"{testcase.test_id}: variables_to_check names unknown variables: "
                + ", ".join(missing)
            )
        result.variables_instrumented = list(testcase.variables_to_check)
    else:
        body, done, skipped = _check_statements(
            testcase.variables_to_check, testcase.expected_values or {}, symbols
        )
        result.variables_instrumented = done
        result.variables_skipped = skipped
        for name, reason in skipped.items():
            result.diagnostics.append(
                Diagnostic(
                    code="W-TESTGEN-UNCHECKABLE",
                    message=f"{name} is not compared in COBOL: {reason}",
                    severity=Severity.WARNING,
                )
            )

    out = _splice(text, insertions)
    if not out.endswith("\n"):
        out += "\n"
    # ZZ-TESTCASE-EOF comes first so that a last paragraph which falls off the
    # end still reports exactly once, and never falls into the trailer bodies.
    trailer = [
        "",
        _comment(">>> TOOL-GENERATED TEST HARNESS <<<"),
        _paragraph_header(EOF_PARAGRAPH),
    ]
    trailer += render_harness_statement(["PERFORM", trailer_paragraph], BODY_INDENT)
    trailer += render_harness_statement(["GOBACK"], BODY_INDENT, period=True)
    trailer += ["", _paragraph_header(trailer_paragraph)] + body + [""]
    result.text = out + "\n".join(trailer) + "\n"
    return result
