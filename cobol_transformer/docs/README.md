# cobol_transformer — Implementation Documentation

Documentation of the AST-driven COBOL → GnuCOBOL transformer, written so you can
explain the pipeline to someone else in detail.

## Read in this order

| # | Document | What it covers |
|---|---|---|
| 1 | [Architecture](01-architecture.md) | The problem, the eight stages, data flow, and the five decisions that shape everything else |
| 2 | [Copybook Inlining](02-copybook-inlining.md) | Stage 1 — the lexer, COPY/INCLUDE scanner, resolver, recursive inliner, BMS map generation |
| 3 | [Detection & Anchoring](03-detection-and-anchoring.md) | Stage 2 — the AST client, node classifier, and the anchoring algorithm that replaces line numbers |
| 4 | [Program Analysis](04-analysis.md) | The symbol table, PICTURE parser, and the EXEC option mini-parser |
| 5 | [Mock Generation](05-mocking.md) | Stage 4 — the rule engine and every built-in CICS/SQL rule, including loop termination |
| 6 | [Rewriting](06-rewriting.md) | Stages 3, 5 and 6 — terminator fidelity, commenting, splicing, declaration injection |
| 7 | [Verification & Reporting](07-verification-and-reporting.md) | Stage 7 — the equivalence proof, manifest, report, and test suite |
| 8 | [End-to-End Walkthrough](08-walkthrough.md) | One real program traced through all eight stages, with actual output |
| 9 | [CLI & Operations](09-cli-and-operations.md) | Subcommands, flags, GnuCOBOL invocation, running the AST server |

## The one-paragraph version

The tool takes a mainframe COBOL program that cannot compile outside z/OS
(because it is full of `EXEC CICS` and `EXEC SQL`), inlines its copybooks so it
is self-contained, finds every construct that needs a mainframe at run time,
**comments that construct out in place**, and inserts a deterministic mock
directly below it. Everything else is copied byte for byte. The claim that
nothing else changed is not asserted — it is *proved* per program by reversing
the transformation and diffing against the input.

## Current results

Scope is the 26 GenApp programs the AST backend can parse. Five programs
(`lgicvs01`, `lgipvs01`, `lgsetup`, `lgstsq`, `lgtestc1`) are excluded: the Z Open
Editor language server refuses to emit an AST for them because its CICS
validator rejects `SEND TEXT ... WAIT` / `ASIS` without `TERMINAL`. A lexical
fallback handles them, but they are out of scope here — see
[Detection](03-detection-and-anchoring.md#the-fallback-and-why-it-is-trustworthy).

| Metric | Result |
|---|---|
| Programs transformed on the AST backend | **26 / 26** |
| Compile with `cobc -x` | **26 / 26** |
| Run to completion | **26 / 26** |
| Verified byte-identical outside mocks | **26 / 26** |
| Constructs mocked | **406** (EXEC blocks + `DFHRESP` macros) |
| Generic-fallback rule used | **0** |
| Constructs skipped | **0** |
| Unit + integration tests | 198 passed, 5 skipped |

(For reference, the full 31-program corpus — including the five that fall back
to the lexical detector — also reaches 31/31 on all four measures.)

The ten programs delivered in `transformed/`:

| Program | Source LOC | Output LOC | Mocks |
|---|---|---|---|
| lgipdb01 | 1030 | 1452 | 25 |
| lgwebst5 | 802 | 957 | 51 |
| lgapdb01 | 595 | 896 | 28 |
| lgupdb01 | 535 | 834 | 23 |
| lgacdb01 | 328 | 606 | 17 |
| lgtestp4 | 318 | 1137 | 20 |
| lgtestp1 | 318 | 1170 | 26 |
| lgtestp2 | 300 | 1138 | 25 |
| lgtestp3 | 299 | 1131 | 25 |
| lgicdb01 | 245 | 518 | 10 |

## Source map

```
cobol_transformer/
  cli.py                 subcommands: inline | detect | transform | build | verify
  pipeline.py            orchestrates all eight stages
  verify.py              reverses the transformation to prove equivalence
  linetools.py           offset <-> line/col, fixed-format column helpers
  errors.py              Diagnostic record + exception hierarchy

  discovery/
    copybook_resolver.py search path, plus built-in SQLCA and generated SSMAP

  inline/                stage 1 - text-level copybook expansion
    lexer.py             per-offset CODE/COMMENT/STRING/EXEC classification
    scanner.py           locates COPY and EXEC SQL INCLUDE
    replacing.py         COPY ... REPLACING substitution
    inliner.py           recursive expansion, cycle detection
    source_map.py        offset -> origin file/line, for diagnostics
    bms.py               BMS macro source -> COBOL symbolic map

  ast_client/            stage 2 - the AST backend
    ast_model.py         AstDocument/AstNode, newline normalisation, walk()
    http_client.py       HTTP client + one-shot CLI fallback

  analysis/
    node_classifier.py   which nodes must not survive verbatim
    anchor.py            verbatim-text anchoring (never line numbers)
    text_detector.py     lexical detection when the AST is unavailable
    symbol_table.py      DATA DIVISION symbols, groups, REDEFINES
    pic_parser.py        PICTURE -> category/length/digits/signed
    exec_text_parser.py  CICS option and SQL clause mini-parser

  mocks/                 stage 4 - mock generation
    rule_engine.py       RuleContext, MockRule, dispatch
    rules_cics.py        per-CICS-verb rules
    rules_sql.py         per-SQL-verb rules incl. cursor lifecycle
    rules_eib.py         DFHRESP substitution + EIB field synthesis
    rules_fallback.py    always-matches safety net
    dummy_values.py      PICTURE + name -> deterministic literal
    var_allocator.py     collision-free synthesized names
    codegen.py           fixed-format emission, terminator-aware
    cics_conditions.json DFHRESP condition name -> numeric value

  rewrite/               stages 3, 5, 6
    terminator.py        detects the original's sentence terminator
    commenter.py         comments a statement's lines, purity-checked
    rewriter.py          the single linear splice pass
    ws_injector.py       EIB fields, mock counters, LINKAGE promotion
    syntax_repair.py     punctuation GnuCOBOL requires

  output/
    manifest.py          TransformationManifest -> JSON
    writer.py            writes .cbl + manifest + report

  gnucobol/
    gnucobol_runner.py   cobc compile/run, WSL path translation
```

45 modules, ~5,000 lines of Python.
