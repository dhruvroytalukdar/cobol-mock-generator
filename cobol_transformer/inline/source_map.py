"""Track which file each region of the expanded text came from.

Used purely for diagnostics and traceability -- never for correctness-critical
logic (design plan section 4.7).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class SourceSpan:
    """A region of the expanded text and the origin it was copied from."""

    start: int                 # offset in expanded text
    end: int                   # offset in expanded text (exclusive)
    origin_file: str           # path of the file the text came from
    origin_line: int           # 1-based first line within that origin file
    copy_chain: Tuple[str, ...] = ()   # copybook names traversed to get here
    occurrence: int = 0        # which occurrence of this copybook this is

    @property
    def from_copybook(self) -> bool:
        return bool(self.copy_chain)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "origin_file": self.origin_file,
            "origin_line": self.origin_line,
            "copy_chain": list(self.copy_chain),
            "occurrence": self.occurrence,
        }


@dataclass
class SourceMap:
    """Offset-sorted, non-overlapping spans covering the whole expanded text."""

    spans: List[SourceSpan] = field(default_factory=list)

    def add(self, span: SourceSpan) -> None:
        if span.end > span.start:
            self.spans.append(span)

    def finalize(self) -> None:
        self.spans.sort(key=lambda s: s.start)
        self._starts = [s.start for s in self.spans]

    def lookup(self, offset: int) -> Optional[SourceSpan]:
        """The span containing ``offset``, or None."""
        starts = getattr(self, "_starts", None)
        if starts is None:
            self.finalize()
            starts = self._starts
        i = bisect.bisect_right(starts, offset) - 1
        if i < 0:
            return None
        span = self.spans[i]
        return span if span.start <= offset < span.end else None

    def origin_of(self, offset: int, text: str) -> Tuple[str, int]:
        """``(origin_file, 1-based origin line)`` for ``offset`` in the expanded text.

        The line is the span's own start line plus however many newlines occur
        between the span start and ``offset``.
        """
        span = self.lookup(offset)
        if span is None:
            return ("<unknown>", 0)
        delta = text.count("\n", span.start, offset)
        return (span.origin_file, span.origin_line + delta)

    def to_dict(self) -> dict:
        return {"spans": [s.to_dict() for s in self.spans]}
