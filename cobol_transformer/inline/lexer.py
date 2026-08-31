"""Per-offset lexical classification of fixed-format COBOL source.

A single forward scan labels every character of the source as CODE, COMMENT,
STRING (inside a quoted literal), IGNORED (sequence area / identification area
/ outside columns 8-72) or EXEC (inside an ``EXEC ... END-EXEC`` block).  Every
later text-level scan consults this mask so that keywords appearing inside
comments or string literals are never mistaken for real statements.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

from ..linetools import AREA_A_START, CODE_END, LineIndex, is_comment_line


class Kind(IntEnum):
    IGNORED = 0   # sequence area, identification area, line endings
    CODE = 1      # ordinary program text
    COMMENT = 2   # a fixed-format comment line
    STRING = 3    # inside a quoted literal
    EXEC = 4      # inside EXEC ... END-EXEC (code, but a distinct region)


_EXEC_START = re.compile(r"\bEXEC\b", re.IGNORECASE)
_END_EXEC = re.compile(r"\bEND-EXEC\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExecBlock:
    """One ``EXEC ... END-EXEC`` region located by the lexer.

    ``start`` is the offset of the ``E`` of ``EXEC``; ``end`` is the offset just
    past the ``C`` of ``END-EXEC``.
    """

    start: int
    end: int
    dialect: str          # "CICS", "SQL" or "UNKNOWN"
    text: str             # verbatim source slice [start, end)
    body: str             # code-only text of the block, comment lines stripped


class SourceLexer:
    """Classifies one COBOL source text and exposes EXEC block boundaries."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.index = LineIndex(text)
        self.kinds: List[int] = [Kind.IGNORED] * len(text)
        self._classify_lines()
        self.exec_blocks: List[ExecBlock] = self._find_exec_blocks()
        self._mark_exec_regions()

    # -- phase 1: line-level and string-literal classification ---------------

    def _classify_lines(self) -> None:
        """Label each character CODE/COMMENT/STRING/IGNORED."""
        text = self.text
        kinds = self.kinds
        for line in range(self.index.line_count):
            ls = self.index.line_start(line)
            le = self.index.line_end(line)
            line_text = text[ls:le]

            if is_comment_line(line_text):
                for i in range(ls, le):
                    kinds[i] = Kind.COMMENT
                continue

            # Only columns 8-72 are program text; the rest stays IGNORED.
            code_start = ls + AREA_A_START
            code_stop = min(ls + CODE_END, le)
            if code_start >= code_stop:
                continue

            in_string = False
            quote = ""
            i = code_start
            while i < code_stop:
                ch = text[i]
                if in_string:
                    kinds[i] = Kind.STRING
                    if ch == quote:
                        # A doubled quote is an escaped quote, not a terminator.
                        if i + 1 < code_stop and text[i + 1] == quote:
                            kinds[i + 1] = Kind.STRING
                            i += 2
                            continue
                        in_string = False
                        quote = ""
                    i += 1
                    continue

                if ch in ("'", '"'):
                    in_string = True
                    quote = ch
                    kinds[i] = Kind.STRING
                    i += 1
                    continue

                kinds[i] = Kind.CODE
                i += 1
            # An unterminated literal simply ends at the line boundary.

    # -- phase 2: EXEC block discovery ---------------------------------------

    def _find_exec_blocks(self) -> List[ExecBlock]:
        """Locate every ``EXEC ... END-EXEC`` pair over CODE-classified text."""
        blocks: List[ExecBlock] = []
        text = self.text
        pos = 0
        while True:
            m = _EXEC_START.search(text, pos)
            if not m:
                break
            start = m.start()
            if self.kinds[start] != Kind.CODE:
                pos = m.end()
                continue
            # END-EXEC itself contains "EXEC"; skip a match that is part of one.
            if start >= 4 and text[start - 4 : start].upper() == "END-":
                pos = m.end()
                continue

            end_m = _END_EXEC.search(text, m.end())
            while end_m and self.kinds[end_m.start()] != Kind.CODE:
                end_m = _END_EXEC.search(text, end_m.end())
            if not end_m:
                # Unterminated EXEC: leave it as ordinary code rather than
                # swallowing the rest of the file.
                pos = m.end()
                continue

            end = end_m.end()
            raw = text[start:end]
            blocks.append(
                ExecBlock(
                    start=start,
                    end=end,
                    dialect=self._dialect_of(raw),
                    text=raw,
                    body=self._body_of(start, end),
                )
            )
            pos = end
        return blocks

    @staticmethod
    def _dialect_of(raw: str) -> str:
        head = raw[:40].upper().split()
        if len(head) >= 2:
            if head[1] == "CICS":
                return "CICS"
            if head[1] == "SQL":
                return "SQL"
        return "UNKNOWN"

    def _body_of(self, start: int, end: int) -> str:
        """Code-only text of an EXEC block: comment lines and columns outside
        8-72 removed, so option parsing never sees commentary or sequence
        numbers."""
        first, last = self.index.lines_spanned(start, end)
        parts: List[str] = []
        for line in range(first, last + 1):
            ls = self.index.line_start(line)
            le = self.index.line_end(line)
            if is_comment_line(self.text[ls:le]):
                continue
            seg_start = max(ls + AREA_A_START, start)
            seg_stop = min(ls + CODE_END, le, end)
            if seg_start < seg_stop:
                parts.append(self.text[seg_start:seg_stop])
        return "\n".join(parts)

    def _mark_exec_regions(self) -> None:
        """Re-label CODE inside EXEC blocks as EXEC (STRING/COMMENT survive)."""
        for blk in self.exec_blocks:
            for i in range(blk.start, blk.end):
                if self.kinds[i] == Kind.CODE:
                    self.kinds[i] = Kind.EXEC

    # -- queries -------------------------------------------------------------

    def kind_at(self, offset: int) -> int:
        if 0 <= offset < len(self.kinds):
            return self.kinds[offset]
        return Kind.IGNORED

    def is_live_code(self, offset: int) -> bool:
        """True when ``offset`` is program text a compiler would act on."""
        return self.kind_at(offset) in (Kind.CODE, Kind.EXEC)

    def exec_block_at(self, offset: int) -> Optional[ExecBlock]:
        for blk in self.exec_blocks:
            if blk.start <= offset < blk.end:
                return blk
        return None
