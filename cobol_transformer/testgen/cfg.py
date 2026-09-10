"""The ground-truth block inventory of one program: the coverage denominator.

v1 tracks two kinds of block, both confirmed against real AST output:

* **paragraph / section entry** -- a line-coverage proxy.  A ``SECTION`` header
  is itself a ``PERFORM``/``GO TO`` target, so it gets its own block covering
  the statements between the header and the first paragraph inside it.
* **IF-THEN / IF-ELSE** -- branch coverage.  An ``IF`` with no ``ELSE``
  contributes only a ``-THEN`` block; no false-path block is fabricated for it.

Anchoring differs from :mod:`analysis.anchor` and the difference matters.  That
module walks the document once with a monotonically advancing cursor, which is
right for the flat list of ``EXEC`` blocks it locates but wrong here for two
reasons: ``IfStatement`` nodes *nest*, so an inner node's text lies inside a
span the cursor has already passed; and the serializer emits grammar slots out
of document order (an ``EndIf`` child appears before the ``ELSE`` token).  So
this module anchors *hierarchically* -- each node is located within the span
already established for its parent, with a retry from the parent's start for
the out-of-order slots.  AST line numbers remain unread, exactly as elsewhere:
position still comes only from verbatim ``Source Text``.

Failure is fail-closed, as in :mod:`analysis.anchor`: a block that cannot be
located is dropped with a diagnostic rather than probed at a guessed offset.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..analysis.symbol_table import SymbolTable, build_symbol_table
from ..ast_client.ast_model import AstDocument, AstNode, normalize_newlines
from ..ast_client.http_client import AstClientConfig, HttpAstClient
from ..discovery.copybook_resolver import CopybookResolver
from ..errors import Diagnostic, Severity
from ..inline.inliner import Inliner
from ..inline.lexer import SourceLexer
from ..linetools import LineIndex
from ..pipeline import _procedure_division_offset

_PARAGRAPH_NODES = ("Paragraph0",)
_SECTION_NODES = ("SectionHeaderParagraph",)
_SECTION_HEADER_NODES = ("SectionHeader0",)


@dataclass
class Block:
    """One instrumentable region of the PROCEDURE DIVISION."""

    id: str
    kind: str                 # paragraph | section | if-then | if-else
    name: str
    line_start: int           # 1-based, inclusive
    line_end: int             # 1-based, inclusive
    #: Offset at which this block's probe statement is inserted.
    probe_offset: int = 0
    #: A paragraph probe is its own sentence; a branch probe must join the
    #: conditional's statement list, so it carries no period of its own.
    probe_period: bool = False
    paragraph: str = ""       # owning paragraph/section, for branch blocks

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }
        if self.paragraph:
            d["paragraph"] = self.paragraph
        return d

    @property
    def line_count(self) -> int:
        return max(self.line_end - self.line_start + 1, 0)


@dataclass
class CoverageManifest:
    program: str
    blocks: List[Block] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    #: Total physical lines of the PROCEDURE DIVISION, the line-coverage base.
    procedure_lines: int = 0

    def to_dict(self) -> dict:
        return {
            "program": self.program,
            "procedure_lines": self.procedure_lines,
            "blocks": [b.to_dict() for b in self.blocks],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }

    def by_id(self) -> Dict[str, Block]:
        return {b.id: b for b in self.blocks}

    def write(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.to_dict(), fh, indent=2)
            fh.write("\n")
        return path


def load_manifest(path: str) -> CoverageManifest:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return CoverageManifest(
        program=raw.get("program", ""),
        procedure_lines=int(raw.get("procedure_lines", 0)),
        blocks=[
            Block(
                id=b["id"], kind=b["kind"], name=b.get("name", ""),
                line_start=b.get("line_start", 0), line_end=b.get("line_end", 0),
                paragraph=b.get("paragraph", ""),
            )
            for b in raw.get("blocks", [])
        ],
    )


# -- hierarchical anchoring -------------------------------------------------

@dataclass
class _Located:
    node: AstNode
    start: int
    end: int


def _flexible(needle: str) -> re.Pattern:
    return re.compile(r"\s+".join(re.escape(p) for p in needle.split()))


def _find(text: str, needle: str, lo: int, hi: int) -> int:
    """Locate ``needle`` in ``text[lo:hi]``, tolerating reflowed whitespace."""
    if not needle:
        return -1
    idx = text.find(needle, lo, hi)
    if idx != -1:
        return idx
    m = _flexible(needle).search(text, lo, hi)
    return m.start() if m else -1


def _overlaps_located(start: int, end: int, out: List[_Located]) -> bool:
    return any(start < loc.end and loc.start < end for loc in out)


def _anchor_tree(text: str, node: AstNode, lo: int, hi: int,
                 out: List[_Located]) -> None:
    """Locate every descendant of ``node``, which itself occupies ``[lo, hi)``."""
    cursor = lo
    for child in node.children:
        needle = child.source_text
        if not needle:
            continue
        idx = _find(text, needle, cursor, hi)
        if idx == -1:
            # Grammar slots are not always in document order (an ``EndIf``
            # child precedes the ``ELSE`` token), so retry from the parent --
            # but if that retry lands on a span an earlier sibling already
            # claimed, this child's text is a genuine duplicate with no real
            # second occurrence, not an out-of-order one.  Accepting the
            # collision would anchor two distinct AST nodes to the identical
            # span, corrupting the coverage manifest's block inventory.
            idx = _find(text, needle, lo, hi)
            if idx != -1 and _overlaps_located(idx, idx + len(needle), out):
                idx = -1
        if idx == -1:
            continue
        end = idx + len(needle)
        if end > hi:
            continue
        out.append(_Located(child, idx, end))
        _anchor_tree(text, child, idx, end, out)
        cursor = max(cursor, end)


def _locate_all(text: str, document: AstDocument) -> List[_Located]:
    root = document.root
    start = _find(text, root.source_text, 0, len(text)) if root.source_text else 0
    if start == -1:
        start = 0
    end = start + len(root.source_text) if root.source_text else len(text)
    located = [_Located(root, start, min(end, len(text)))]
    _anchor_tree(text, root, located[0].start, located[0].end, located)
    return located


# -- block extraction -------------------------------------------------------

def _prop(node: AstNode, key: str) -> str:
    value = node.properties.get(key)
    return normalize_newlines(str(value)) if value is not None else ""


def _body_offset_after_header(text: str, header_end: int, limit: int) -> int:
    """Offset just past the period that closes a paragraph/section header."""
    dot = text.find(".", header_end, limit)
    return dot + 1 if dot != -1 else header_end


def _unique(ids: Dict[str, int], base: str) -> str:
    ids[base] = ids.get(base, 0) + 1
    return base if ids[base] == 1 else f"{base}-{ids[base]}"


def build_manifest(text: str, document: AstDocument, program: str) -> CoverageManifest:
    """Extract every paragraph/section and IF/ELSE block from ``text``."""
    manifest = CoverageManifest(program=program)
    index = LineIndex(text)
    lexer = SourceLexer(text)
    proc_offset = _procedure_division_offset(text, lexer)
    text_end = len(text)
    manifest.procedure_lines = (
        index.line_of(text_end - 1) - index.line_of(proc_offset) + 1
        if text_end > proc_offset else 0
    )

    located = _locate_all(text, document)
    ids: Dict[str, int] = {}

    # -- paragraphs and sections, in document order ------------------------
    routines: List[Tuple[int, int, str, str, int]] = []   # start, end, kind, name, probe
    for item in located:
        node, kind, name = item.node, "", ""
        if node.node_type in _SECTION_NODES:
            header = node.child_named("SectionHeader0")
            name = _prop(header, "_SectionName") if header else ""
            kind = "section"
        elif node.node_type in _PARAGRAPH_NODES:
            name = _prop(node, "_ParagraphName")
            kind = "paragraph"
        else:
            continue
        if not name or item.start < proc_offset:
            continue
        probe = _body_offset_after_header(text, item.start, item.end)
        routines.append((item.start, item.end, kind, name.upper(), probe))

    routines.sort(key=lambda r: r[0])
    starts = [r[0] for r in routines]
    for i, (start, end, kind, name, probe) in enumerate(routines):
        # A routine's own block ends where the next routine begins, so a
        # section's block covers only the statements above its first paragraph.
        # Snapping to that header's line start keeps consecutive ranges from
        # overlapping on the shared line, which would double-count lines.
        if i + 1 < len(starts):
            stop = index.line_start(index.line_of(starts[i + 1]))
        else:
            stop = max(end, start + 1)
        first, last = index.lines_spanned(start, stop)
        manifest.blocks.append(
            Block(
                id=_unique(ids, f"PARA-{name}"),
                kind=kind,
                name=name,
                line_start=first + 1,
                line_end=last + 1,
                probe_offset=probe,
                probe_period=True,
            )
        )

    # -- IF / ELSE ---------------------------------------------------------
    routine_spans = [(r[0], r[3]) for r in routines]

    def owning_routine(offset: int) -> str:
        owner = ""
        for start, name in routine_spans:
            if start <= offset:
                owner = name
            else:
                break
        return owner

    ifs = sorted(
        (it for it in located
         if it.node.node_type == "IfStatement" and it.start >= proc_offset),
        key=lambda it: it.start,
    )
    for seq, item in enumerate(ifs, start=1):
        node = item.node
        tag = f"IF-{seq:04d}"
        owner = owning_routine(item.start)
        then_text = _prop(node, "_StatementNextSentence")
        then_at = _find(text, then_text, item.start, item.end) if then_text else -1
        if then_at == -1:
            # Fall back to the end of the condition; if that is unavailable
            # the block is dropped rather than probed at a guessed offset.
            cond = _prop(node, "_Condition")
            cond_at = _find(text, cond, item.start, item.end) if cond else -1
            if cond_at == -1:
                manifest.diagnostics.append(
                    Diagnostic(
                        code="W-CFG-IF-NOT-LOCATED",
                        message=(
                            f"{tag}: neither the then-body nor the condition could "
                            "be located inside the IfStatement span; block skipped"
                        ),
                        severity=Severity.WARNING,
                        detail={"snippet": node.source_text[:120]},
                    )
                )
                continue
            then_at = cond_at + len(cond)

        else_text = _prop(node, "_StatementNextSentence6")
        else_at = -1
        if _prop(node, "_ELSE") and else_text:
            else_at = _find(text, else_text, then_at, item.end)

        then_stop = else_at if else_at != -1 else item.end
        first, last = index.lines_spanned(then_at, then_stop)
        manifest.blocks.append(
            Block(
                id=f"{tag}-THEN", kind="if-then", name=tag,
                line_start=first + 1, line_end=last + 1,
                probe_offset=then_at, probe_period=False, paragraph=owner,
            )
        )
        if else_at != -1:
            first, last = index.lines_spanned(else_at, item.end)
            manifest.blocks.append(
                Block(
                    id=f"{tag}-ELSE", kind="if-else", name=tag,
                    line_start=first + 1, line_end=last + 1,
                    probe_offset=else_at, probe_period=False, paragraph=owner,
                )
            )

    manifest.blocks.sort(key=lambda b: (b.probe_offset, b.id))
    return manifest


# -- loading a program's sources -------------------------------------------

@dataclass
class ProgramSources:
    """The canonical text of one transformed program, plus what is derived."""

    program: str
    path: str
    text: str
    symbols: SymbolTable


def load_program(transformed_dir: str, program: str) -> ProgramSources:
    """Read ``<transformed_dir>/<program>.cbl`` as the canonical text.

    Copybooks are expanded even though a transformed program has none left, so
    that the text instrumented, the text sent to the AST server and the text
    compiled are the same string in every case.
    """
    path = os.path.join(transformed_dir, f"{program}.cbl")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"no transformed program at {path}")
    resolver = CopybookResolver([], source_dir=os.path.dirname(os.path.abspath(path)))
    inlined = Inliner(resolver, continue_on_missing=True).inline_file(path)
    text = normalize_newlines(inlined.text)
    return ProgramSources(
        program=program, path=path, text=text, symbols=build_symbol_table(text)
    )


def manifest_for(
    sources: ProgramSources, ast_url: str = "http://127.0.0.1:4010"
) -> CoverageManifest:
    """Build the coverage manifest for ``sources`` from a fresh AST."""
    document = HttpAstClient(AstClientConfig(base_url=ast_url)).get_ast(
        sources.text, os.path.basename(sources.path)
    )
    return build_manifest(sources.text, document, sources.program)
