"""Recursive, text-level copybook expansion.

Runs before the AST tool ever sees the source, so the tool receives one
physically complete file (design plan section 4).  Copybook text is normalised
to fixed format on the way in: a copybook whose lines start in column 1 would
otherwise put data-division text in the sequence area, where the compiler
ignores it.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..discovery.copybook_resolver import CopybookResolver
from ..errors import CopybookCycleError, CopybookNotFoundError
from ..errors import Diagnostic, Severity
from ..linetools import AREA_A_START, CODE_END, LineIndex, is_comment_line
from .replacing import apply_replacing, parse_replacing
from .scanner import scan_copy_statements
from .source_map import SourceMap, SourceSpan


@dataclass
class InlineResult:
    text: str
    source_map: SourceMap
    diagnostics: List[Diagnostic] = field(default_factory=list)
    copybooks_used: Dict[str, int] = field(default_factory=dict)  # name -> occurrences


_SEQUENCE_NUMBER = re.compile(r"^\d{1,6}$")


def normalize_fixed_format(text: str) -> str:
    """Shift copybook text into columns 8-72 when it starts in the sequence area.

    Copybooks in this corpus are already fixed-format, but a copybook written
    flush-left (or a generated one) would land in columns 1-7 and be silently
    dropped by the compiler.  Comment lines keep their indicator in column 7.

    A numeric sequence number legitimately occupying columns 1-6 (e.g. AWS
    CardDemo's copybooks, which carry "000100", "000200", ... on every line)
    must not be mistaken for flush-left content: shifting a line so its own
    sequence number lands in Area A turns that number into bogus program text
    and breaks the compile.  Only non-numeric content there indicates a real
    flush-left line.
    """
    out: List[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("")
            continue
        if is_comment_line(line):
            out.append(line)
            continue
        seq_area = line[:AREA_A_START - 1].strip()
        if seq_area and not _SEQUENCE_NUMBER.match(seq_area):
            stripped = line.lstrip()
            out.append(" " * AREA_A_START + stripped)
        else:
            out.append(line)
    return "\n".join(out)


class Inliner:
    """Expands COPY / EXEC SQL INCLUDE recursively, building a source map."""

    def __init__(
        self,
        resolver: CopybookResolver,
        continue_on_missing: bool = False,
    ) -> None:
        self.resolver = resolver
        self.continue_on_missing = continue_on_missing
        self.diagnostics: List[Diagnostic] = []
        self.copybooks_used: Dict[str, int] = {}

    def inline_file(self, path: str) -> InlineResult:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return self.inline_text(text, os.path.abspath(path))

    def inline_text(self, text: str, origin: str) -> InlineResult:
        smap = SourceMap()
        out: List[str] = []
        self._expand(text, origin, out, smap, chain=(), stack=[origin], out_len=[0])
        smap.finalize()
        return InlineResult(
            text="".join(out),
            source_map=smap,
            diagnostics=list(self.diagnostics),
            copybooks_used=dict(self.copybooks_used),
        )

    # -- recursive worker ----------------------------------------------------

    def _expand(
        self,
        text: str,
        origin: str,
        out: List[str],
        smap: SourceMap,
        chain: Tuple[str, ...],
        stack: List[str],
        out_len: List[int],
    ) -> None:
        """Append the fully expanded form of ``text`` to ``out``.

        ``out_len`` is a single-element list used as a mutable counter of the
        total output length so far, which is the offset base for source spans.
        """
        index = LineIndex(text)
        statements = scan_copy_statements(text)
        cursor = 0

        def whole_line_span(start: int, end: int) -> Tuple[int, int]:
            """Widen ``[start, end)`` to whole lines when only blanks surround it.

            A COPY / EXEC SQL INCLUDE statement occupies its own line(s); taking
            the whole line means the generated banner comment starts in column 1
            (so its ``*`` lands in the indicator column) instead of being
            appended after the statement's leading indentation.
            """
            first, last = index.lines_spanned(start, end)
            ls, le = index.line_start(first), index.line_end(last)
            if text[ls:start].strip() or text[end:le].strip():
                return start, end  # shares a line with other code: leave it alone
            return ls, min(le + 1, len(text))

        def emit(chunk: str, origin_offset: int) -> None:
            if not chunk:
                return
            start = out_len[0]
            out.append(chunk)
            out_len[0] += len(chunk)
            smap.add(
                SourceSpan(
                    start=start,
                    end=out_len[0],
                    origin_file=origin,
                    origin_line=index.line_col(origin_offset)[0],
                    copy_chain=chain,
                    occurrence=self.copybooks_used.get(chain[-1], 0) if chain else 0,
                )
            )

        for stmt in statements:
            stmt_start, stmt_end = whole_line_span(stmt.start, stmt.end)
            emit(text[cursor:stmt_start], cursor)

            try:
                book = self.resolver.resolve(stmt.name, stmt.library)
            except CopybookNotFoundError as exc:
                if not self.continue_on_missing:
                    raise
                line = index.line_col(stmt.start)[0]
                self.diagnostics.append(
                    Diagnostic(
                        code="W-COPYBOOK-MISSING",
                        message=str(exc),
                        severity=Severity.WARNING,
                        file=origin,
                        line=line,
                    )
                )
                placeholder = (
                    f"      * >>> MISSING COPYBOOK {stmt.name}: {stmt.form} not resolved\n"
                )
                emit(placeholder, stmt.start)
                cursor = stmt_end
                continue

            self.copybooks_used[book.name] = self.copybooks_used.get(book.name, 0) + 1

            real_path = book.path
            if not book.synthesized and real_path in stack:
                raise CopybookCycleError(
                    "COPY cycle detected: " + " -> ".join(stack + [real_path])
                )

            body = normalize_fixed_format(
                book.text.replace("\r\n", "\n").replace("\r", "\n")
            )
            if stmt.replacing:
                body = apply_replacing(body, parse_replacing(stmt.replacing))

            # Keep the original statement visible as a comment so the expanded
            # file still records where each copybook came from.
            banner = (
                f"      * >>> BEGIN {stmt.form} {stmt.name}"
                f" ({os.path.basename(real_path)})\n"
            )
            emit(banner, stmt.start)

            if not body.endswith("\n"):
                body += "\n"
            # Recurse so nested COPY inside a copybook is expanded too.
            self._expand(
                body,
                real_path,
                out,
                smap,
                chain=chain + (book.name,),
                stack=stack + [real_path],
                out_len=out_len,
            )

            emit(f"      * <<< END {stmt.form} {stmt.name}\n", stmt.start)
            cursor = stmt_end

        emit(text[cursor:], cursor)
