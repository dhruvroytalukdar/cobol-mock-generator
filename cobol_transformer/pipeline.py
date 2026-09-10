"""Sequence every stage of the transformation.

    validate -> inline copybooks -> AST (or text fallback) -> classify+anchor
    -> terminator -> mock rules -> comment+insert -> inject declarations
    -> write output (-> compile)

The AST is preferred, but a program the language server refuses to parse still
transforms: detection falls back to the lexical scanner, which was verified to
produce byte-identical spans on every corpus program where both paths run.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .analysis.anchor import ReplacementRange, anchor_nodes
from .analysis.exec_text_parser import parse_exec
from .analysis.node_classifier import Category, NodeClassifier
from .analysis.symbol_table import build_symbol_table
from .analysis.text_detector import detect_by_text
from .ast_client.ast_model import normalize_newlines
from .ast_client.http_client import AstClientConfig, HttpAstClient
from .discovery.copybook_resolver import CopybookResolver
from .errors import AstUnavailableError, Diagnostic, Severity
from .inline.inliner import Inliner
from .inline.lexer import Kind, SourceLexer
from .linetools import LineIndex
from .mocks.codegen import render_statements
from .mocks.dummy_values import DummyValueConfig
from .mocks.rule_engine import RuleContext, build_default_engine
from .mocks.rules_eib import referenced_eib_fields
from .mocks.var_allocator import VarAllocator
from .output.manifest import ConstructRecord, TransformationManifest
from .rewrite.rewriter import rewrite
from .rewrite.syntax_repair import repair
from .rewrite.terminator import annotate_terminators
from .rewrite.ws_injector import inject

_PROC_DIVISION = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.IGNORECASE)
# A paragraph or section header starts in Area A (columns 8-11), i.e. within the
# first four characters of the code area.  Anchoring to Area A is what keeps a
# line such as "           END-EXEC." from being read as a paragraph name.
_PARAGRAPH = re.compile(r"^\s{0,3}([A-Z0-9][A-Z0-9-]*)\s*(?:SECTION\s*)?\.\s*$",
                        re.IGNORECASE)
_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.\s*([A-Za-z0-9$#@_-]+)", re.IGNORECASE)


@dataclass
class PipelineOptions:
    copybook_dirs: List[str] = field(default_factory=list)
    continue_on_missing_copybook: bool = True
    promote_linkage: bool = True
    use_ast: bool = True
    ast_url: str = "http://127.0.0.1:4010"
    seed: int = 1
    rows_per_cursor: int = 1


@dataclass
class PipelineResult:
    expanded_text: str
    output_text: str
    manifest: TransformationManifest
    diagnostics: List[Diagnostic] = field(default_factory=list)


def _procedure_division_offset(text: str, lexer: SourceLexer) -> int:
    for m in _PROC_DIVISION.finditer(text):
        if lexer.kind_at(m.start()) == Kind.CODE:
            return m.start()
    return len(text)


def _paragraph_map(
    text: str, index: LineIndex, proc_offset: int, lexer: SourceLexer
) -> List[tuple]:
    """``(offset, name)`` for each paragraph/section header, in order."""
    out: List[tuple] = []
    for line in range(index.line_count):
        start = index.line_start(line)
        if start < proc_offset:
            continue
        raw = index.line_text(line)
        if len(raw) < 8 or raw[6:7] in ("*", "/"):
            continue
        # Text inside an EXEC block is not program structure, however it looks.
        if lexer.kind_at(start + 7) == Kind.EXEC:
            continue
        code = raw[7:72].rstrip()
        m = _PARAGRAPH.match(code)
        if m and m.group(1).upper() not in ("EXIT", "END-EXEC"):
            out.append((start, m.group(1).upper()))
    return out


def _paragraph_at(paragraphs: List[tuple], offset: int) -> str:
    name = "MAINLINE"
    for off, nm in paragraphs:
        if off <= offset:
            name = nm
        else:
            break
    return name


def run(path: str, options: Optional[PipelineOptions] = None) -> PipelineResult:
    """Transform one COBOL program end to end."""
    opts = options or PipelineOptions()
    diagnostics: List[Diagnostic] = []
    source_dir = os.path.dirname(os.path.abspath(path))

    # -- 1. inline copybooks ------------------------------------------------
    resolver = CopybookResolver(opts.copybook_dirs, source_dir=source_dir)
    inliner = Inliner(resolver, continue_on_missing=opts.continue_on_missing_copybook)
    inlined = inliner.inline_file(path)
    expanded = normalize_newlines(inlined.text)
    diagnostics.extend(inlined.diagnostics)

    # Punctuation repairs run before anything computes an offset, so the
    # canonical text every later stage indexes into is already well formed.
    repaired = repair(expanded)
    expanded = repaired.text
    diagnostics.extend(repaired.diagnostics)

    program = os.path.splitext(os.path.basename(path))[0].upper()
    m = _PROGRAM_ID.search(expanded)
    if m:
        program = m.group(1).upper()

    # -- 2. detect constructs: AST first, lexical scan as fallback ----------
    lexer = SourceLexer(expanded)
    backend = "text-fallback"
    ast_error: Optional[str] = None
    detection = None

    if opts.use_ast:
        client = HttpAstClient(AstClientConfig(base_url=opts.ast_url))
        try:
            document = client.get_ast(expanded, os.path.basename(path))
            detection = anchor_nodes(expanded, document, NodeClassifier(), lexer)
            backend = "ast"
        except AstUnavailableError as exc:
            ast_error = str(exc)
            diagnostics.append(
                Diagnostic(
                    code="W-AST-UNAVAILABLE",
                    message=(
                        "AST backend could not parse this program; using the "
                        f"lexical detector instead ({str(exc)[:160]})"
                    ),
                    severity=Severity.WARNING,
                )
            )
    if detection is None:
        detection = detect_by_text(expanded, lexer)

    diagnostics.extend(detection.diagnostics)
    ranges: List[ReplacementRange] = detection.ranges

    # -- 3. terminator analysis --------------------------------------------
    annotate_terminators(expanded, ranges)

    # -- 4. generate mocks --------------------------------------------------
    symbols = build_symbol_table(expanded, lexer)
    index = LineIndex(expanded)
    proc_offset = _procedure_division_offset(expanded, lexer)
    paragraphs = _paragraph_map(expanded, index, proc_offset, lexer)
    engine = build_default_engine()
    values = DummyValueConfig(seed=opts.seed)
    cursor_state: Dict[str, int] = {}
    allocator = VarAllocator(symbols)

    generated: Dict[int, List[str]] = {}
    inline_text: Dict[int, str] = {}
    meta: Dict[int, Dict] = {}

    for seq, rng in enumerate(ranges):
        command = None
        if rng.category in (Category.CICS, Category.SQL, Category.EXEC_UNKNOWN):
            node = rng.node
            body = node.embedded_text if node is not None else ""
            if not body:
                body = rng.source_text
            dialect = {
                Category.CICS: "CICS",
                Category.SQL: "SQL",
            }.get(rng.category, "UNKNOWN")
            command = parse_exec(body, dialect)

        first, _ = index.lines_spanned(rng.start, rng.term_end)
        from .linetools import area_b_indent_of

        ctx = RuleContext(
            range=rng,
            command=command,
            category=rng.category,
            symbols=symbols,
            indent=area_b_indent_of(index.line_text(first)),
            had_trailing_period=rng.had_trailing_period,
            declarative=rng.start < proc_offset,
            paragraph=_paragraph_at(paragraphs, rng.start),
            sequence=seq,
            program=program,
            values=values,
            cursor_state=cursor_state,
            config={"rows_per_cursor": opts.rows_per_cursor},
            allocator=allocator,
        )
        rule, result = engine.dispatch(ctx)
        meta[rng.start] = {
            "rule_name": rule.name,
            "confidence": result.confidence,
            "diagnostics": result.diagnostics,
            "verb": ctx.verb,
        }
        if result.inline_text is not None:
            inline_text[rng.start] = result.inline_text
        elif result.statements:
            generated[rng.start] = render_statements(
                result.statements, ctx.indent, rng.had_trailing_period
            )
        elif rng.had_trailing_period and not ctx.declarative:
            # A procedural construct that generates no statement still has to
            # carry its sentence terminator, and CONTINUE is the no-op that can.
            # A *declarative* one must not: its period belonged to a data-
            # division entry, and any statement here would not compile.
            generated[rng.start] = render_statements(["CONTINUE"], ctx.indent, True)

    # -- 5. comment originals, insert mocks --------------------------------
    rewritten = rewrite(expanded, ranges, generated, inline_text, meta)
    diagnostics.extend(rewritten.diagnostics)

    # -- 6. declarations: EIB synthesis + LINKAGE promotion ----------------
    eib_needed = referenced_eib_fields(rewritten.text, symbols)
    injected = inject(
        rewritten.text,
        eib_needed,
        promote_linkage=opts.promote_linkage,
        extra_items=allocator.render_block(),
    )
    diagnostics.extend(injected.diagnostics)

    # -- 7. manifest --------------------------------------------------------
    manifest = TransformationManifest(
        program=program,
        source_path=os.path.abspath(path),
        output_path="",
        detection_backend=backend,
        ast_error=ast_error,
        copybooks={
            name: {
                "occurrences": count,
                "path": resolver.resolved[name].path if name in resolver.resolved else "",
                "synthesized": (
                    resolver.resolved[name].synthesized if name in resolver.resolved else False
                ),
            }
            for name, count in inlined.copybooks_used.items()
        },
        synthesized_fields=injected.added_fields
        + [i.name for i in allocator.items],
        linkage_promoted=injected.linkage_promoted,
        diagnostics=[d.to_dict() for d in diagnostics],
    )

    for entry in rewritten.entries:
        rng = entry.range
        line_start, line_end = index.lines_spanned(rng.start, rng.term_end)
        origin_file, origin_line = inlined.source_map.origin_of(rng.start, expanded)
        info = meta.get(rng.start, {})
        manifest.constructs.append(
            ConstructRecord(
                original_file=os.path.basename(origin_file),
                original_line=origin_line,
                expanded_line_start=line_start + 1,
                expanded_line_end=line_end + 1,
                node_type=rng.node.node_type if rng.node else "",
                category=rng.category.value,
                verb=info.get("verb", ""),
                raw_text=" ".join(rng.source_text.split())[:200],
                had_trailing_period=rng.had_trailing_period,
                matched_rule=entry.rule_name,
                confidence=entry.confidence,
                status=entry.status,
                # Injection added lines after the rewriter recorded these, so
                # they are shifted to point at the final output.
                commented_line_start=injected.shift(entry.commented_lines[0]),
                commented_line_end=injected.shift(entry.commented_lines[1]),
                inserted_line_start=injected.shift(entry.inserted_lines[0]),
                inserted_line_end=injected.shift(entry.inserted_lines[1]),
                already_commented_lines=[
                    injected.shift(ln) for ln in entry.already_commented_lines
                ],
                generated_text=entry.generated,
                diagnostic_codes=[d.code for d in entry.diagnostics],
            )
        )

    return PipelineResult(
        expanded_text=expanded,
        output_text=injected.text,
        manifest=manifest,
        diagnostics=diagnostics,
    )
