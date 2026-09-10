"""Produce the transformed source in one linear pass.

For each located construct, in document order:

* a **statement** has all of its physical lines commented out, and the generated
  mock is inserted immediately below them;
* a **sub-expression** (``DFHRESP(...)``) is substituted in place, because it
  lives inside a statement that must keep compiling.

Text outside a located range is copied byte for byte, so comments, blank lines,
indentation, paragraph structure and every unmocked statement survive exactly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..analysis.anchor import ReplacementRange
from ..errors import Diagnostic
from ..linetools import LineIndex
from .commenter import build_comment_block, purity_error


@dataclass
class RewriteEntry:
    """What happened to one construct, for the manifest."""

    range: ReplacementRange
    status: str
    generated: List[str] = field(default_factory=list)
    commented_lines: Tuple[int, int] = (0, 0)
    inserted_lines: Tuple[int, int] = (0, 0)
    already_commented_lines: Tuple[int, ...] = ()
    rule_name: str = ""
    confidence: str = "high"
    diagnostics: List[Diagnostic] = field(default_factory=list)


@dataclass
class RewriteResult:
    text: str
    entries: List[RewriteEntry] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)


def rewrite(
    text: str,
    ranges: List[ReplacementRange],
    generated: Dict[int, List[str]],
    inline_text: Dict[int, str],
    meta: Optional[Dict[int, Dict]] = None,
) -> RewriteResult:
    """Splice mocks into ``text``.

    ``generated`` maps a range's start offset to its mock statement lines;
    ``inline_text`` maps a sub-expression range's start offset to its
    replacement text.  Ranges that appear in neither are left untouched.
    """
    index = LineIndex(text)
    meta = meta or {}
    ordered = sorted(ranges, key=lambda r: r.start)

    out: List[str] = []
    entries: List[RewriteEntry] = []
    diagnostics: List[Diagnostic] = []
    cursor = 0
    out_line = 0  # 0-based line count of the text emitted so far

    def emit(chunk: str) -> None:
        nonlocal out_line
        if chunk:
            out.append(chunk)
            out_line += chunk.count("\n")

    for rng in ordered:
        info = meta.get(rng.start, {})
        rule_name = info.get("rule_name", "")
        confidence = info.get("confidence", "high")
        rule_diags = info.get("diagnostics", [])

        if rng.start < cursor:
            diagnostics.append(
                Diagnostic(
                    code="E-RANGE-OVERLAP",
                    message=f"range at {rng.start} overlaps earlier output; skipped",
                )
            )
            entries.append(RewriteEntry(rng, "skipped_overlap", rule_name=rule_name))
            continue

        # -- sub-expression: substitute in place, keep the line live ---------
        if not rng.is_statement:
            replacement = inline_text.get(rng.start)
            if replacement is None:
                entries.append(
                    RewriteEntry(rng, "skipped_no_replacement", rule_name=rule_name)
                )
                continue
            emit(text[cursor : rng.start])
            start_line = out_line
            emit(replacement)
            entries.append(
                RewriteEntry(
                    range=rng,
                    status="substituted_in_place",
                    generated=[replacement],
                    inserted_lines=(start_line + 1, out_line + 1),
                    rule_name=rule_name,
                    confidence=confidence,
                    diagnostics=list(rule_diags),
                )
            )
            cursor = rng.end
            continue

        # -- statement: comment the original, insert the mock below ---------
        impure = purity_error(text, index, rng)
        if impure is not None:
            diagnostics.append(impure)
            entries.append(
                RewriteEntry(
                    rng,
                    "skipped_comment_line_not_pure",
                    rule_name=rule_name,
                    diagnostics=[impure],
                )
            )
            continue  # leave the source untouched

        block = build_comment_block(text, index, rng)
        block_start = index.line_start(block.first_line)
        block_stop = index.line_end(block.last_line)

        emit(text[cursor:block_start])

        commented_start = out_line
        emit("\n".join(block.lines))
        emit("\n")
        commented_stop = out_line

        mock_lines = generated.get(rng.start, [])
        inserted_start = out_line
        if mock_lines:
            emit("\n".join(mock_lines))
            emit("\n")
        inserted_stop = out_line

        # Skip the original line ending; the block already emitted one.
        cursor = block_stop + 1 if block_stop < len(text) else len(text)

        already_commented_lines = tuple(
            commented_start + 1 + offset
            for offset, was_comment in enumerate(block.already_comment)
            if was_comment
        )

        entries.append(
            RewriteEntry(
                range=rng,
                status="commented_and_mocked" if mock_lines else "commented_only",
                generated=list(mock_lines),
                commented_lines=(commented_start + 1, commented_stop),
                inserted_lines=(inserted_start + 1, inserted_stop),
                already_commented_lines=already_commented_lines,
                rule_name=rule_name,
                confidence=confidence,
                diagnostics=list(rule_diags),
            )
        )

    emit(text[cursor:])
    return RewriteResult(text="".join(out), entries=entries, diagnostics=diagnostics)
