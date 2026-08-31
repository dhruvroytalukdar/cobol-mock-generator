# AST-Driven COBOL → GNUCOBOL Self-Contained Transpiler — Design Plan

## Context

The `genapp-files\src` directory holds IBM's 31-program "GenApp" mainframe COBOL sample (CICS + DB2 + VSAM insurance/customer app), plus a separate single-program sample (`lgacdb01\cobol\LGACDB01.cbl`). None of these programs can be compiled or run today outside a real z/OS CICS+DB2 environment: every program references CICS EIB fields and issues `EXEC CICS`/`EXEC SQL` commands, and "file I/O" in this codebase is done exclusively through `EXEC CICS READ/WRITE/REWRITE/DELETE FILE(...)` against VSAM KSDS files — there is no native `SELECT`/`FD`/`OPEN` anywhere. The goal is a Python tool that takes one such program (plus whatever copybooks it needs), inlines the copybooks so the file is self-contained, and mechanically **comments out** each mainframe-runtime-dependent statement in place (never deletes it) and inserts a deterministic, meaningful mock directly below it — so the result compiles and runs under GNUCOBOL in WSL while keeping every other line of business logic byte-for-byte as originally written, and every mocked construct remains visible and diffable against the original.

This matters because a text/regex-based transformer would be fragile against COBOL's flexible free-text EXEC blocks, comment conventions, and copybook expansion — the user has an existing Java CLI (wrapping IBM's Z Open Editor language server) that emits a real parse tree (`ast\out.json` is a sample), and wants the transformation driven off that tree wherever the tree is trustworthy, falling back to well-justified text-level handling only where the tree is provably blind (verified during investigation below).

**Scope for this iteration**: only the 31 `.cbl` programs (and their `.cpy` copybooks) in `genapp-files\src` are in scope. All node-type coverage, corpus assumptions (e.g. "every EXEC CICS/SQL statement occupies its own physical line(s), never sharing a line with unrelated code"), and fixture selection below are validated against this directory only. `lgacdb01\cobol\LGACDB01.cbl` and any other dialect/corpus are explicitly out of scope for now and not assumed to satisfy the same assumptions.

Three parallel research passes (AST schema, GenApp corpus, Java CLI internals) plus a Plan-agent architecture pass were completed before writing this plan. Their findings are folded in directly rather than repeated as a research log.

---

## 1. Repository Findings & Current-State Assessment

### 1.1 Repo layout (greenfield for Python)

```
cobol-ast-generator-java-cli/
├── README.md                    # Java CLI + HTTP server usage docs
├── cobol-ast-cli.sh/.bat        # one-shot CLI wrapper → com.ibm.zta.cobolast.CobolAstCli
├── cobol-ast-server.sh/.bat     # long-lived HTTP server wrapper → CobolAstHttpServer
├── target/cobol-ast-generator.jar   # the ONLY compiled artifact; no Java source in this repo
├── ast/out.json                 # sample AST (2.4MB) — generated from genapp-files/src/lgacdb01.cbl
├── genapp-files/src/             # 31 .cbl + 11 .cpy real GenApp corpus (flat directory)
└── lgacdb01/                     # a second, differently-formatted copy of the same program + its 2 copybooks
```

No Java source, no Python code, and no test suite exist anywhere in this repo. **Repo-hygiene footnote**: `ast/out.json` was verified (mixed-case identifiers like `Obtain-CUSTOMER-Number`, `GENAcount`) to have been generated from `genapp-files\src\lgacdb01.cbl`, *not* from `lgacdb01\cobol\LGACDB01.cbl` as the folder naming suggests — the two are logically equivalent rewrites with different casing/line breaks. No action needed; just don't assume the sample AST's line numbers correlate to the uppercase file.

### 1.2 The AST generator is a black-box external dependency

`com.ibm.zta.cobolast.CobolAstCli`/`CobolAstHttpServer` are pre-built (only `.class` files in the jar, no `.java` in this checkout). They drive IBM's Z Open Editor language server over LSP, sending a custom `cobol.ast.serialize` (or `v2.cobol.ast.serialize`) request after `initialize`/`didOpen`. Requires **Java 21** + the IBM Z Open Editor VS Code extension installed locally (`~/.vscode/extensions/ibm.zopeneditor-*`). The Python tool must shell out to (or HTTP-call) this tool — it cannot inspect or modify its internals.

Two integration surfaces:
- **CLI** (`cobol-ast-cli.sh/.bat`): one JVM/OSGi boot per invocation, writes `<basename>-ast.json` or `--output <path>`.
- **HTTP server** (`cobol-ast-server.sh/.bat`): one long-lived LSP session reused across `POST /generate-ast` calls (raw text + `X-Filename` header, or a ZIP). **This is the right choice for our pipeline** — we'll call this dozens of times across 31 programs and want to amortize the ~seconds-scale JVM/Equinox boot cost.

`--copybooks <dir>` (repeatable) is supported by the CLI, but section 1.3 explains why we don't use it.

### 1.3 AST schema — verified structure, and three hard limitations

Every node: `{"Node": "<TypeName>", "Source Text": "<verbatim substring>", "properties": {...}, "Children": [...]}` (leaves omit `Children`). This is a full concrete syntax tree (2,842 nodes / 89 distinct `Node` types / up to 23 levels deep for one ~350-line program), not an abstracted AST — even a single identifier reference costs 4-5 tree levels.

**Limitation 1 — line numbers are unreliable.** `properties.stmtStartLineNumber`/`stmtEndLineNumber`/`columnStart`/`columnEnd` are all strings and drift non-linearly from true physical line numbers deeper into a file (empirically verified: offset changes from −13 to −17 partway through one file), sometimes `end < start` on container nodes, and copybook-derived items carry the *copybook's own* line numbers with zero provenance marker. **Only `Source Text` (an exact verbatim substring) is trustworthy.**

**Limitation 2 — `EXEC CICS`/`EXEC SQL` blocks are opaque.** Both produce a `Node: "ExecEndExec"`, distinguished by `properties._SqlOrCics == "CICS"|"SQL"`. The command is *not* semantically parsed — `properties.embeddedLanguageObject` holds the complete raw, unparsed text between `EXEC .../END-EXEC`. `Children` is only crude word tokenization, not structured options (no "COMMAREA option" node). **A hand-written mini-parser over `embeddedLanguageObject` is required** to extract CICS options (`COMMAREA(x)`, `LENGTH(x)`, `RESP(x)`, `RIDFLD(x)`, `FILE('x')`, `ABCODE('x')`, ...) and SQL clauses.

**Limitation 3 — `COPY`/`EXEC SQL INCLUDE` are (partially) invisible.** There is no `CopyStatement` node type at all — copied data items are silently spliced into e.g. `WorkingStorageSection`'s children with zero provenance. **`EXEC SQL INCLUDE ... END-EXEC` produces no node whatsoever** — the text falls in a gap between two sibling nodes' spans, invisible even as raw text. **Copybook boundaries must therefore be resolved at the text level, never via the AST.**

By contrast, ordinary statements (`MoveStatement0`, `IfStatement`, `Perform`, `AddStatement0`, `InitializeStatement0`, `SetStatement1`) and `DataDescriptionEntry1/2/4` (DATA DIVISION items, with `LevelNumber`/`PictureClause`/`DataValueClause`/`UsageClause`/`RedefinesClause` children) are fully structured and reliable to walk directly. No native file-I/O node types (`OpenStatement`, etc.) were observed, only because the sample corpus never uses them — see 1.4.

### 1.4 GenApp corpus findings that shape the mock catalog

- 3-tier architecture: menu/UI (`lgtestc1`, `lgtestp1-4`, BMS-driven) → business logic (`*us01`/`*ol01`, pure `EXEC CICS LINK` orchestration) → persistence (`*db01`/`*db02` = DB2 via `EXEC SQL`, `*vs01` = VSAM via `EXEC CICS READ/WRITE/REWRITE/DELETE FILE(...)`). No native COBOL `CALL`, no `XCTL`, no `STARTBR`/`READNEXT`/`ENDBR`, no `COMP-3`.
- CICS verb frequency (31 programs): LINK(95), RETURN(84), SEND(52), Counter DELETE/DEFINE/QUERY(38/37/36), ABEND(24), FORMATTIME/ASKTIME(22/22), TSQ READQ/WRITEQ/DELETEQ(7/18/6), RECEIVE(13), SYNCPOINT(10), HANDLE AID/CONDITION(10), ASSIGN(9), VSAM READ/WRITE/REWRITE(4/2/2), GET COUNTER/CONTAINER(4), ENQ/DEQ(2/2), START(1).
- SQL verbs (9/31 programs): INCLUDE(19, invisible to AST), INSERT(9), SELECT(8), UPDATE(5), cursor DECLARE/OPEN/FETCH/CLOSE(3 each, in `lgipdb01.cbl` and `lgupdb01.cbl`), SET-from-special-register(2), DELETE(1).
- Two VSAM KSDS files, both accessed only via CICS: `KSDSCUST`, `KSDSPOLY`. Read directly (`genapp-files\src\lgucvs01.cbl`, in full): a `READ FILE('KSDSCUST') INTO(...) LENGTH(...) RIDFLD(...) KEYLENGTH(10) RESP(WS-RESP) UPDATE` → `IF WS-RESP NOT = DFHRESP(NORMAL)` error branch (`ABEND`+`RETURN`) → `REWRITE FILE('KSDSCUST') FROM(...) LENGTH(...) RESP(WS-RESP)` → same error-branch pattern. This read-check-rewrite-check shape repeats across all `*vs01` programs.
- Copybooks: `LGCMAREA` (22 programs — one 32.5KB commarea, 3-way then 5-way nested `REDEFINES`, read in full), `LGPOLICY` (6 programs — DB2 length constants + host-variable groups), `SSMAP` (5 menu programs — BMS symbolic map). **No `REPLACING` used anywhere in the real corpus**, and copybooks are one level deep (no nested `COPY`) — so nested-COPY and `REPLACING` support must be validated with synthetic fixtures, not real ones.
- Mainframe pseudo-registers needing mock support: `EIBCALEN`(123), `DFHCOMMAREA`(124), `SQLCODE`(102), `LENGTH OF`(82), `EIBTRNID`(17), `DFHRESP`(18 — a condition-value macro used *inside* ordinary `IF` conditions, e.g. `IF WS-RESP NOT = DFHRESP(NORMAL)`; this one **is** structurally visible in the AST as a `CicsDFHRESPmacro` node, unlike the opaque EXEC blocks), `SQLCA`(16), `POINTER`/`ADDRESS OF`(15/15), `EIBRESP`(7).
- Best fixture candidates by tier: simplest (`lgstsq.cbl`, 126 lines/7 CICS/0 SQL), CICS-heavy (`lgsetup.cbl` 533 lines/84 cmds, `lgwebst5.cbl` 802 lines/50 cmds), SQL-focused (`lgicdb01.cbl`, single SELECT), VSAM read+rewrite (`lgucvs01.cbl`), kitchen-sink (`lgipdb01.cbl` 1030 lines/2 cursors, `lgupdb01.cbl` 535 lines/1 cursor+UPDATE+dual LINK), BMS/pseudo-conversational (`lgtestc1.cbl`).

---

## 2. Proposed Architecture

New top-level package `cobol_transform/` (Python, `pyproject.toml` at repo root), designed to run **entirely inside WSL** (recommended default — see §9.1) alongside the Java tool and `cobc`.

```
cobol_transform/
  cli.py                # argparse entry point: inline | detect | transform | build subcommands
  pipeline.py            # orchestrator sequencing every stage
  config.py               # RuleEngineConfig + pipeline config (YAML/JSON) loader
  errors.py                # Diagnostic dataclass + exception hierarchy
  linetools.py              # LineIndex (offset<->line/col), COBOL Area A/B column helpers

  discovery/
    input_validator.py       # main-file existence/encoding/fixed-format sanity
    copybook_resolver.py      # search-path resolution (--copybooks dirs, source dir, extensions, OF/IN)

  inline/                     # TEXT-LEVEL copybook inlining (runs BEFORE the AST tool — see §4)
    lexer.py                   # per-offset CODE/COMMENT/STRING_LITERAL/EXEC_BLOCK classification
    scanner.py                  # locates COPY / EXEC SQL INCLUDE spans, document order
    replacing.py                 # REPLACING: identifier/literal/pseudo-text substitution
    inliner.py                    # recursive expansion: cycle detection, per-occurrence re-expansion
    source_map.py                  # SourceSpan records + offset->origin lookup (diagnostics only)

  ast_client/
    base.py                # AstClient interface: get_ast(source_text, filename_hint) -> AstDocument
    http_client.py          # POSTs to CobolAstHttpServer /generate-ast (preferred)
    subprocess_client.py     # shells out to cobol-ast-cli.sh/.bat (fallback)
    ast_model.py               # AstDocument; pre-order DFS walk() over Children

  analysis/
    symbol_table.py         # DATA DIVISION symbol table (name/level/PIC/USAGE/parent/redefines)
    pic_parser.py             # PICTURE clause text -> category/digits/decimals/signed
    node_classifier.py         # unsupported-node predicate registry
    exec_text_parser.py         # CICS option tokenizer + SQL light extractors over embeddedLanguageObject
    anchor.py                    # anchored sequential substring search -> ReplacementRange list

  mocks/
    rule_engine.py           # RuleContext, MockRule interface, registry+dispatch
    rules_cics.py              # built-in per-CICS-verb rules
    rules_sql.py                 # built-in per-SQL-verb rules (incl. cursor lifecycle)
    rules_eib.py                   # DFHRESP()/DFHRESP2() literal substitution + EIB field synthesis
    rules_fallback.py                # generic safe-default rule (always matches last)
    dummy_values.py                    # PIC-category -> deterministic literal, name-based heuristics
    var_allocator.py                     # collision-free synthesized WORKING-STORAGE naming
    codegen.py                             # emits Area A/B-correct COBOL text at a given indent, terminator-aware (see §5.2)
    cics_conditions.json                     # DFHRESP/EIBRESP condition-name -> numeric value table

  rewrite/
    terminator.py            # structurally detects whether a matched node's sentence ends in a period (§5.2)
    commenter.py               # converts each physical line touched by a ReplacementRange into a COBOL comment line, line-purity-checked
    rewriter.py                  # single linear insert pass: comments original span in place, inserts generated mock text immediately below it, over sorted non-overlapping ReplacementRanges
    ws_injector.py                 # inserts synthesized WORKING-STORAGE block, AST-anchored

  output/
    writer.py                # writes final .cbl + sourcemap.json + manifest.json + report.txt
    manifest.py                # TransformationManifest dataclass + JSON (de)serialization

  compile/
    wsl_bridge.py            # WSL invocation/path handling (only needed if NOT already running in WSL)
    gnucobol_runner.py         # cobc compile [+run], captures exit code/stdout/stderr

tests/
  unit/          # scanner, replacing, inliner (nested/cycle), source_map, exec_text_parser,
                 # anchor, dummy_values, var_allocator, symbol_table — all AST/Java-independent
  integration/    # one test per fixture tier, @pytest.mark.needs_java
  fixtures/
    genapp/        # pointers into genapp-files/src (real corpus)
    synthetic/       # hand-built REPLACING / nested-copy / cycle / duplicate-EXEC fixtures
    golden/             # checked-in expected transformed output + manifest

```

**Data flow**: `input_validator` → `copybook_resolver` + `inline.*` (produces `expanded_text` + `SourceMap`) → `ast_client` (AST of `expanded_text`) → `analysis.symbol_table` (built from AST) + `analysis.node_classifier`/`anchor` (produces ordered `ReplacementRange` list, each annotated by `rewrite.terminator` with whether its sentence ends in a period) → `mocks.rule_engine` (turns each range into generated COBOL text, terminator-matched, using the symbol table for context) → `rewrite.commenter` (comments out every physical line the range touches, line-purity-checked) + `rewrite.rewriter` (inserts the generated mock text immediately below the commented block) + `ws_injector` (injects new WORKING-STORAGE) → `output.writer` (final `.cbl` + manifest + report) → `compile.*` (optional `cobc` validation in WSL).

---

## 3. CLI / User Workflow

`cobol_transform <subcommand> [options]`, argparse-based, subcommands mirror pipeline stages so users can stop at any point:

- `inline MAIN.cbl [--copybooks DIR ...] [-o OUT.cbl]` — copybook resolution + inlining only; writes expanded source + `sourcemap.json`. Dry-run friendly.
- `detect MAIN.cbl [--copybooks DIR ...]` — runs inlining + AST + classification, prints a human-readable table of every unsupported construct found (verb, location in *original* file via the source map, category) without writing any output — the "analysis/dry-run mode" the user asked for.
- `transform MAIN.cbl [--copybooks DIR ...] [--rule-config rules.yaml] [-o OUT.cbl] [--manifest OUT.manifest.json] [--report OUT.report.txt]` — full pipeline, writes the self-contained transformed file plus diagnostics artifacts. `--dry-run` prints the planned replacements without writing the `.cbl`.
- `build MAIN.cbl ... [--run] [--gnucobol-flags "..."]` — `transform` then invoke `cobc` (and optionally run the resulting executable) via `compile.gnucobol_runner`, surfacing compiler errors verbatim.

Common flags across subcommands: `--copybooks DIR` (repeatable, matches the Java CLI's own convention for familiarity), `--continue-on-missing-copybook` (emit placeholder + warning instead of hard-aborting), `--seed N` (deterministic-but-configurable dummy values), `--verbose`/`--quiet`.

---

## 4. Copybook Inlining Strategy

**Decision: inline copybooks as a pure text-level pass, before the AST tool ever runs.** This is forced by §1.3/Limitation 3 — the AST cannot see `COPY`/`INCLUDE` boundaries reliably (COPY: silent, unmarked; INCLUDE: fully invisible) — and it has the added benefit that once inlining is done, the AST tool receives one physically complete file, eliminating that entire class of problem for every later stage rather than working around it per-stage.

1. **Lexical masking** (`inline/lexer.py`): one forward scan classifying every offset as `CODE`/`COMMENT` (indicator column 7 = `*`/`/`)/`STRING_LITERAL` (quote-aware, doubled-quote escaping)/`EXEC_BLOCK` (between `EXEC` and matching `END-EXEC`). Prevents false positives (e.g. "COPY" inside a comment or an EXEC CICS string literal).
2. **Statement scan** (`inline/scanner.py`): regex-locate `COPY <name>[ OF/IN <lib>][ REPLACING ...].` and, within `EXEC_BLOCK` spans, `EXEC SQL INCLUDE <name> END-EXEC.` — the latter is treated as an alternate copybook-inclusion syntax equivalent to `COPY`, and is **the only place `EXEC SQL INCLUDE` is ever handled** in the whole pipeline, since it never reaches the AST. Only matches whose start falls in a `CODE`/`EXEC_BLOCK`-appropriate span (not `COMMENT`/`STRING_LITERAL`) are accepted.
3. **Resolution** (`discovery/copybook_resolver.py`): search order = each `--copybooks DIR` in order given, then the main file's own directory (matches the flat `genapp-files\src` layout) — extensions tried `.cpy`/`.CPY`/`.cbl`/`.CBL`, case-insensitive. `OF`/`IN <lib>` is a best-effort optional-subdirectory hint (no real example exercises it — documented limitation, not silently dropped). Not-found is a hard error by default, naming file+line (reliable pre-AST) and the copybook; `--continue-on-missing-copybook` substitutes a commented placeholder and continues.
4. **Recursive expansion with cycle detection** (`inline/inliner.py`): resolving a copybook re-runs the identical scan on its own text (handles nested COPY generally). A stack of in-progress absolute paths detects cycles and hard-aborts with the full chain.
5. **Duplicate COPY — deliberately not memoized.** Each occurrence (even of the same copybook name) is independently re-expanded, matching true COBOL macro semantics (REPLACING may differ per occurrence; each needs its own source-map entry).
6. **REPLACING** (`inline/replacing.py`): parsed into ordered `(pattern, replacement, mode)` triples — `identifier`/`literal` (whole-word, case-insensitive) and `pseudo_text` (`==...==`-delimited, token-sequence matched with whitespace-run tolerance). Applied left-to-right, each scanning forward past its own replacement to guarantee termination. Since no `REPLACING` exists in the real corpus, this path's correctness bar is unit tests on synthetic fixtures — called out as residual risk.
7. **Splicing**: a single incremental string-builder walk (never `str.replace`, which would break on duplicate copybook names) — append untouched text up to each span, append the recursively-expanded copybook text, advance cursor; append the tail at the end. Builds `expanded_text` and, in the same walk, a `SourceMap` (offset-sorted `SourceSpan` records: origin file, origin line range via direct newline counting in that file's own text, copy-chain, occurrence index) used **only for diagnostics/traceability**, never for correctness-critical logic downstream.

**Declarations vs. procedural copybooks**: no special-casing needed — both are handled by the same text-splice mechanism; a copybook containing `EXEC SQL DECLARE ... TABLE` statements (as `LGPOLICY.cpy` does) simply becomes ordinary physical text that the AST tool later parses as normal `ExecEndExec`/data-item nodes, indistinguishable in kind from main-program content.

---

## 5. AST-Driven Transformation Algorithm

**Run the AST tool against `expanded_text`** (POST to the HTTP server's `/generate-ast` with `X-Filename` = original basename — preferred over the subprocess CLI to avoid a JVM boot per program across 31+ runs). No `--copybooks` flag is needed or used at this stage — there are no COPY boundaries left. Normalize line endings to `\n` once before sending, and never re-normalize afterward: this exact byte sequence is the single canonical text every offset (search side and splice side) is computed against.

**`AstDocument.walk()`**: pre-order DFS over `Children`. **Load-bearing assumption**: children arrays reflect physical document order — this is what makes anchoring by sequential forward search valid. A cheap defensive self-check (below) validates this rather than trusting it blindly.

**Unsupported-node detection** (`analysis/node_classifier.py`): a registry of `(name, predicate, category)`. Built-ins: `is_exec_cics`/`is_exec_sql` (`Node == "ExecEndExec"`, `_SqlOrCics` discriminates). On a match, the node is recorded and its subtree is **not** descended (children of `ExecEndExec` are only crude re-tokenization of the same span, not independently meaningful). Extensible for future node types (native file I/O, if ever encountered) without touching the anchoring machinery.

**Anchored sequential substring search** (`analysis/anchor.py`) — solves the line-number-unreliability problem by never using line numbers at all:

1. `cursor = 0`.
2. For each unsupported node in document order: `needle = node["Source Text"]`; `idx = expanded_text.find(needle, cursor)`.
3. **Not found** → hard failure, fail-closed: skip transformation for this node (leave its source untouched), emit a diagnostic (`E-ANCHOR-NOT-FOUND` if not found anywhere, `E-ANCHOR-OUT-OF-ORDER` if it's found only *before* `cursor`, indicating a broken document-order assumption), and never advance the cursor on a guess. An un-mocked construct that fails `cobc` compilation is a visible, fixable failure; a mis-anchored replacement silently corrupting unrelated code is not acceptable.
4. **Found** → record `ReplacementRange(start=idx, end=idx+len(needle), node)`, `cursor = idx + len(needle)`.
5. Post-pass assertion: `ranges[i].end <= ranges[i+1].start` for all `i` — structurally guaranteed by tree semantics + monotonic cursor, validated rather than assumed; violation hard-aborts the run rather than emitting corrupted output.

This is robust to duplicate/whitespace-identical spans (e.g. two identical `EXEC CICS ABEND ...` blocks) precisely because each search starts where the previous one ended and nodes are visited in physical order — a naive `str.replace` or "search from 0 each time" would incorrectly collapse both onto the first occurrence.

**Offset → line/col for diagnostics** (`linetools.LineIndex`): precomputed newline-offset list over `expanded_text`, bisected per lookup. **AST line-number properties are never read anywhere in the pipeline** — by design, given §1.3/Limitation 1.

### 5.1 Comment-preserving insertion, not replacement

**The original statement is never deleted.** For each `ReplacementRange`, the pipeline comments out every physical line the range touches (turning it into inert COBOL text) and inserts the generated mock statement(s) immediately below the commented block, at the same Area B indent column. This makes every mocked construct visible and diffable in the output file — a reviewer sees exactly what was mocked and what it was replaced with, in place, rather than having to consult the manifest to know something was removed.

`rewrite/commenter.py` does the line-level work:
1. Given a `ReplacementRange`'s `[start, end)` byte offsets (extended to include a trailing terminator period per §5.2 if one belongs to this statement), use `LineIndex` to find the first and last physical line the range touches.
2. **Line-purity check (fail-closed):** if any character on the first line before `start`, or on the last line after the (possibly terminator-extended) `end`, is non-whitespace, the range is rejected — logged as `E-COMMENT-LINE-NOT-PURE`, and the node is skipped exactly like an anchor failure (§5, step 3) rather than risking commenting-out unrelated live code that happens to share the line. This is safe to assume will essentially never fire on the current corpus: §1.4's own inspection of `EXEC CICS`/`EXEC SQL` usage across all 31 `genapp-files\src` programs shows every such statement already starts and ends on its own line(s) — but the check exists so a violation is a visible, diagnosable failure rather than silent corruption.
3. For every physical line in range, force column 7 (the fixed-format indicator column) to `*`, leaving columns 1-6 and 8-72 untouched — this is the same comment convention already used natively throughout the corpus, so no dialect-specific `*>` inline-comment syntax is introduced. Continuation lines (original indicator `-`) are commented the same way; their content survives as inert text.
4. `rewrite/rewriter.py` then inserts the mock text (from `mocks.rule_engine`, terminator-matched per §5.2) as new line(s) immediately following the last commented line, before continuing the linear pass over the rest of `expanded_text`.

Because insertion adds lines rather than doing a byte-range substitution, and downstream nothing re-indexes by original line number (line/col for the manifest is recomputed from the *output* text via a fresh `LineIndex`, per §5 above), this doesn't disturb any other invariant already in the plan. Everything outside a touched range — other comments, indentation, blank lines, paragraph/section structure, `GO TO`/`PERFORM`/`IF`/fall-through logic — survives byte-for-byte, exactly as before.

### 5.2 Statement terminator (period) handling

COBOL periods are sentence terminators, not per-statement punctuation: a `.` ends the enclosing sentence and — critically inside `IF`/`PERFORM`/`EVALUATE` bodies — can end that scope early if inserted or dropped in the wrong place. The corpus is inconsistent about whether an `EXEC CICS`/`EXEC SQL` statement is the last statement of its sentence (followed by a period) or is one statement among several in the same sentence (followed directly by another statement, no period). **Simply always emitting a period after the mock, or never emitting one, would silently change control flow** — exactly the risk being guarded against here.

The fix is to preserve whatever terminator situation already existed, rather than infer or standardize one:

1. `rewrite/terminator.py` determines, for each matched node's `ReplacementRange`, whether it is immediately followed by a sentence-terminating period: scan `expanded_text` forward from `end` past whitespace/newlines (not past any other token) for the next non-blank character. If it is a `.` immediately followed by whitespace/newline/EOF (never a digit, which would make it a decimal point — not reachable here since `end` is the close of a statement, not mid-literal), it belongs to this statement; record `had_trailing_period = True` and extend the range's `end` to include that period (so it gets commented out along with the rest of the statement in §5.1, rather than left dangling live outside a comment). Otherwise `had_trailing_period = False` and `end` is unchanged.
2. This period is recorded structurally per node, before any commenting happens, and is threaded into `RuleContext` (§6.1) so `mocks/codegen.py` can honor it.
3. `codegen.py` emits the generated mock as one or more complete simple statements (`DISPLAY`, `MOVE`, ...), which never require their own scope terminator:
   - if `had_trailing_period` is `True`, the **last** generated statement ends with `.`, restoring the original sentence boundary exactly where it was;
   - if `had_trailing_period` is `False`, no period is emitted after the last generated statement — the mock simply continues the same sentence into whatever statement originally followed, matching the original flow exactly.
4. This is verified with a dedicated unit test pair before Phase 3 lands: one fixture where an `EXEC CICS` statement is followed by a period, one where it is immediately followed by another statement in the same sentence (both patterns exist in `genapp-files\src`, e.g. inside `IF WS-RESP NOT = DFHRESP(NORMAL)` blocks in `lgucvs01.cbl` — see §1.4) — asserting the mock reproduces the same terminator presence/absence as the original.

### 5.3 Multi-line vs single-line statements

No special-casing is needed for line count. `Source Text` already spans the full construct (`EXEC`...`END-EXEC` inclusively, or a single-line `MoveStatement`/etc.) regardless of how many physical lines it occupies — one `ReplacementRange` covers the whole thing either way. `rewrite/commenter.py` (§5.1) comments every physical line the range's offsets touch, whether that's one line or twenty, using the same `LineIndex`-based line enumeration in both cases; there is no line-count-dependent branch anywhere in the commenting or insertion logic. The only place line count matters at all is diagnostics (the manifest reports a line *range*, not a single line, when the original spanned more than one).

**Embedded sub-expressions (`DFHRESP(...)`)**: these appear *inside* otherwise-fully-structured statements (e.g. an `IfStatement`'s condition) as a `CicsDFHRESPmacro` node — not an `ExecEndExec`, so untouched by the primary pass, yet not compilable by GNUCOBOL as-is. Handled by generalizing "unsupported node" from "statement" to "any node whose Source Text must not survive verbatim": add a `CicsDFHRESPmacro` predicate to `node_classifier`, reuse the identical anchor/comment/insert machinery (§5.1). Note this node sits *inside* a live, still-compiling condition (e.g. `IF WS-RESP NOT = DFHRESP(NORMAL)`) — commenting out its containing line would break the enclosing `IF`, so this one case is an exception to §5.1's line-comment strategy: `DFHRESP(...)`/`DFHRESP2(...)` are substituted **in place**, character-for-character, with a numeric literal from `mocks/cics_conditions.json` (NORMAL=0, NOTFND=13, DUPREC=15, DUPKEY=17, ...) — a true replacement, not a comment-and-insert, and carries no terminator concern since it's a sub-expression, not a statement.

**Correctness guarantees this design provides** (mapping directly to the user's requirement #7):
- Only nodes matched by a registered classifier predicate are ever touched — everything else (data definitions, control-flow statements, labels) is guaranteed untouched because it's simply never in the `ReplacementRange` list, and neither the commenter nor the rewriter ever rewrites text outside those ranges.
- The original statement text is never deleted — it is commented out in place (§5.1) and left directly above its generated mock, so the transformed file remains a full, reviewable record of every change.
- `GO TO`/`PERFORM`/fall-through/conditional structure is preserved both because those statements are not classified as unsupported and never touched, and because §5.2's terminator matching guarantees a commented-and-mocked statement neither opens nor closes a sentence/scope boundary differently than the original did.
- Replacement text is always emitted as complete, terminator-matched COBOL statements (§5.2, §6) at the same Area B indent column as the statement it replaces (inferred from the original span's column via `LineIndex`), so scope/terminator validity is a `codegen.py` responsibility, verified per-rule in unit tests.
- New variables are only ever appended to `WORKING-STORAGE SECTION` (never DATA DIVISION-wide guessing) via `ws_injector.py`, anchored off the AST's own `WorkingStorageSection` span using the same anchor mechanism — never a blind text insertion.
- Determinism: no wall-clock/random values are used anywhere in generated code by default (all dummy values come from static tables/config, optionally a `--seed`), and the anchor algorithm has no nondeterministic tie-breaking.
- Traceability: the original source is never modified in place on disk — `transform` always writes to a new output path — and within that output, the original statement is preserved (commented) rather than erased; the `SourceMap` + manifest additionally let every generated line be traced back to (a) the original file/line it mocks and (b) which copybook (if any) contributed the surrounding declarations.

---

## 6. Mocking Strategy

### 6.1 Rule engine

`RuleContext`: node, `sql_or_cics`, `verb`, raw text, parsed `options`, symbol table, enclosing paragraph/section, inferred indent column, source span, monotonic sequence id (for unique naming), config.

`MockRule`: `matches(ctx) -> bool`, `generate(ctx) -> MockResult{statements, new_working_storage_items, diagnostics}`.

Dispatch order: config-file `verb_overrides` (highest priority — override behavior with no code change) → built-in verb-specific rules (`rules_cics.py`, `rules_sql.py`) → `rules_fallback.GenericFallbackRule` (always matches last, so **every** unsupported node gets *some* mock — reaching it for a recognized verb also emits a `W-FALLBACK-RULE-USED` diagnostic so coverage gaps stay visible rather than silent).

### 6.2 Unsupported-construct classification & per-category behavior

| Category | AST detection | Context extracted | Mock behavior | Return-code/status handling |
|---|---|---|---|---|
| **CICS program-to-program** (LINK, RETURN, SEND, RECEIVE, ABEND, ASSIGN, SYNCPOINT, HANDLE AID/CONDITION, ENQ/DEQ, START) | `ExecEndExec`, `_SqlOrCics=CICS`, verb from first token | Options via mini-parser (`PROGRAM`/`COMMAREA`/`LENGTH`/`ABCODE`/`TRANSID`); symbol table for referenced fields | `DISPLAY` trace line naming the verb+target+key fields; for LINK, leave the commarea buffer untouched by default (target behavior is unknowable in general — safe default, see open question) unless a configured naming convention (`*-RETURN-CODE`/`*-RESP`) is detected in the commarea, in which case `MOVE 0` (success) to it | `RESP()`/`RESP2()` options get `MOVE 0 TO <resolved-field>` — a raw numeric literal, never `DFHRESP(NORMAL)` (which is itself unsupported — see §5) |
| **CICS counters/TSQ/TDQ** (GET COUNTER, DEFINE/DELETE/QUERY COUNTER, READQ/WRITEQ/DELETEQ TS/TD) | same | `POOL`/`COUNTER`/`QUEUE`/`ITEM`/`VALUE` options | `MOVE` a deterministic (configurable-seed) integer into the target `VALUE`/`INTO` field; `DISPLAY` trace | `RESP` per above |
| **CICS date/time** (ASKTIME, FORMATTIME) | same | `ABSTIME`/`MMDDYYYY`/`TIME` options | `MOVE` fixed deterministic date/time literals (length-appropriate, e.g. `PIC X(8)`/`X(10)`) | n/a |
| **CICS VSAM file ops** (READ/WRITE/REWRITE/DELETE FILE) | same | `FILE`/`INTO`/`FROM`/`RIDFLD`/`KEYLENGTH`/`RESP` options; symbol table for the target record layout | For READ: `MOVE` dummy values into every field of the `INTO` record structure (walking its group hierarchy via the symbol table, per-field by PIC category — see §6.3), then `DISPLAY` a trace showing the key(s) read. For WRITE/REWRITE: `DISPLAY` the `FROM` record's key fields (echoing what "would have been written"). For DELETE: `DISPLAY` the key. | `RESP` → success (0) by default; `--rule-config` can force a specific `(program, verb, occurrence)` to a failure `RESP` (e.g. NOTFND=13) for negative-path fixtures |
| **Embedded SQL — INSERT/UPDATE/DELETE** | `ExecEndExec`, `_SqlOrCics=SQL`, verb-specific light extractor | table name, host-variable list (`:X` tokens) | `DISPLAY` a trace line with table + host-variable values (looked up via symbol table); if the statement's target used `IDENTITY_VAL_LOCAL()`-style `SET`, that companion statement gets its own rule setting the host var to a deterministic incrementing integer | `MOVE 0 TO SQLCODE` (SQLCODE field must already exist — see §6.4) |
| **Embedded SQL — single-row SELECT** | same | `INTO` host-var list, table, raw `WHERE` (opaque) | `MOVE` dummy values into every `INTO` host variable per its PIC category; `DISPLAY` trace | `MOVE 0 TO SQLCODE` (success = row found); config can force `MOVE 100 TO SQLCODE` (not-found) for negative fixtures |
| **Embedded SQL — cursor lifecycle** (DECLARE/OPEN/FETCH/CLOSE) | same, tracked as a stateful group keyed by cursor name | cursor name, associated SELECT's `INTO` list | DECLARE/OPEN/CLOSE → no-op `DISPLAY` only; FETCH → same `INTO`-population as single-row SELECT, plus (to keep any enclosing `PERFORM ... UNTIL SQLCODE = 100`-style loop from running forever) the mock tracks a per-cursor call counter and returns `SQLCODE = 100` (not-found, ends the loop) starting from the **second** FETCH by default — configurable row count | `MOVE 0`/`MOVE 100 TO SQLCODE` per above |
| **`EXEC SQL INCLUDE`** | Not an AST concern — resolved entirely by the copybook inliner (§4) as an alternate COPY syntax; the underlying data items (e.g. `SQLCA`'s `SQLCODE` field) become ordinary compilable WORKING-STORAGE/LINKAGE text | n/a | n/a — no replacement needed; GNUCOBOL compiles plain PIC clauses regardless of DB2 runtime absence | n/a |
| **`DFHRESP(...)`/`DFHRESP2(...)` sub-expressions** | `CicsDFHRESPmacro` node (§5) | condition-value name (e.g. `NORMAL`) | Replace with the numeric literal from `mocks/cics_conditions.json` | n/a |
| **Unrecognized EXEC CICS/SQL verb** (generic fallback) | reached `GenericFallbackRule` | raw text only | `DISPLAY` the raw command text prefixed `'DUMMY EXEC: '`; `MOVE 0` to any `RESP`/`RESP2`/`SQLCODE` field found by scanning the raw text for those tokens against the symbol table | success by default; emits `W-FALLBACK-RULE-USED` |
| **Native COBOL file I/O** (OPEN/READ/WRITE/CLOSE/START/REWRITE/DELETE against a real `FD`) | *No node type confirmed empirically — none exist in the current corpus.* Predicate slots reserved in `node_classifier`; exact `Node` type names to be confirmed the first time a real fixture with `FILE-CONTROL`/`FD` is fed through Phase 2 (see §9.2, open question) | `SELECT`/`ASSIGN`/`FD` record layout | Same per-field dummy-population strategy as CICS VSAM READ, generalized once node types are confirmed | File status field (`FILE STATUS IS ...`) set to `'00'` (success) by default |
| **Mainframe compiler directives / vendor pragmas** (if encountered, e.g. `CBL`/`PROCESS` options tuned for Enterprise COBOL) | text-scan fallback (these are not statement nodes, they're compiler-directive lines) — flagged as out-of-AST-scope like `EXEC SQL INCLUDE`, handled by a small text-level directive-stripper pass alongside the inliner | directive name | Comment out (never silently drop — replace with `*> STRIPPED DIRECTIVE: <original text>`) | n/a |
| **`POINTER`/`ADDRESS OF`/`SET ... TO ADDRESS OF`** | Fully structured, ordinary statements (`UsageClause`, `SetStatement1`) — GNUCOBOL supports `POINTER`/`ADDRESS OF` natively, just with different runtime semantics than Enterprise COBOL | n/a | **Not replaced** — left as-is; flagged in the manifest as a "compiles but semantics may differ" advisory, not a hard-replaced construct | n/a |

**When to fail safely instead of guessing**: any node matched as unsupported but whose `embeddedLanguageObject`/raw text the mini-parser cannot confidently tokenize (parse error in the option scanner) falls through to the generic fallback rule rather than a verb-specific rule guessing at options — the fallback's raw-`DISPLAY`+success-RESP behavior is always safe to emit even with zero semantic understanding of the command. Anchor failures (§5) are the other fail-safe path: skip and diagnose, never guess a location.

### 6.3 Dummy value conventions (`mocks/dummy_values.py`)

Ordered, config-overridable `(predicate_on_name_and_pic, value_fn)` list:
- **Numeric** (`PIC 9...`/`COMP`/`COMP-3`/`BINARY`): `0` by default (success-path convention); a configurable non-zero seed for fields whose name suggests generated output (contains `NUM`/`ID`/`COUNT`).
- **Alphanumeric** (`PIC X...`): `'DUMMY'`, space-padded/truncated to exact PIC length — **unless** the name suggests a date (`DATE`, length 8/10 → fixed deterministic date literal) or time (`TIME`, length 6/8 → fixed deterministic time literal) or a single-char flag/indicator (length 1, name contains `FLAG`/`IND`/`SW` → configurable default character).
- **Group fields**: walked recursively via the symbol table's parent/child hierarchy (built from `REDEFINES`/level-number nesting), each elementary leaf populated per its own PIC category — `REDEFINES` siblings are never double-populated (only the *active* interpretation being read/written by the specific statement is touched, per the field list the statement's own options actually reference).
- **Pointer/USAGE POINTER fields**: left `SET TO NULL` or untouched — never given a fabricated numeric value (would be meaningless and risks GNUCOBOL runtime errors on dereference).

### 6.4 Return-code, status-field, and `DISPLAY` conventions

- Success is always the numeric literal `0` (never a `DFHRESP(...)`/special-register call, which is itself unsupported).
- Every generated `DISPLAY` line uses a consistent, greppable prefix: `'>>> MOCK <verb> @<paragraph>: '` followed by key field values — this both aids manual test verification and gives the manifest/report a stable string to correlate against captured stdout during `build --run`.
- **Deterministic-but-configurable testing**: all of §6.3's defaults, the RESP/SQLCODE success/failure policy, and per-`(program, verb, occurrence-index)` overrides live in one `--rule-config` YAML — this is how a test author scripts a specific negative-path scenario (e.g. force the 3rd `EXEC CICS READ FILE('KSDSCUST')` to return `NOTFND`) without touching generated code by hand.

### 6.5 New-variable policy, naming, and collision avoidance

**Minimize synthesis.** SQLCA/DCLGEN-derived fields (`SQLCODE`, etc.) are never synthesized fresh — if `EXEC SQL INCLUDE SQLCA` was present, its expansion is now plain compilable WORKING-STORAGE data (§6.2), and mock rules simply `MOVE` into the existing field. New items are synthesized only for:
1. **EIB fields** (`rules_eib.py`): any `EIB`-prefixed identifier referenced with no matching declaration triggers a one-time-per-program synthesis of the standard EIB field group, inserted via `ws_injector.py`.
2. Rare rule-specific scratch fields with no natural home — minimized by preferring literal `DISPLAY`s over intermediate variables wherever possible.

`var_allocator.py` guarantees collision-free names by checking the full case-insensitive symbol table and appending numeric suffixes on collision. All synthesized items are grouped under a banner comment (`* >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<`) and appended at the end of `WORKING-STORAGE SECTION`, located by anchoring off the AST's own `WorkingStorageSection` node span — never a blind text insertion, and never disturbing existing `REDEFINES`/group alignment.

---

## 7. Diagnostics, Manifest & Reporting

`output/manifest.py` — `TransformationManifest` (JSON), one entry per detected construct:
```
{
  original_location: {file, line_start, line_end, col}   # via SourceMap, traces through copybook origin
  expanded_location: {line_start, line_end, col}          # via LineIndex over expanded_text, pre-comment
  node_type, sql_or_cics, verb, raw_text
  had_trailing_period: true|false             # from rewrite.terminator (§5.2)
  matched_rule, confidence: "high"|"fallback"
  commented_location: {line_start, line_end}  # where the original now lives as a comment, in output text
  inserted_location: {line_start, line_end}   # where the generated mock was inserted, in output text
  generated_text
  variables_referenced: [...]                # from symbol table lookups
  status: "commented_and_mocked" | "substituted_in_place" | "skipped_anchor_error" | "skipped_comment_line_not_pure" | "skipped_missing_copybook_placeholder"
  diagnostic_codes: [...]                     # e.g. W-FALLBACK-RULE-USED, E-COMMENT-LINE-NOT-PURE
}
```
`status: "substituted_in_place"` is reserved for the one true in-place character substitution case, `DFHRESP(...)`/`DFHRESP2(...)` sub-expressions (§5, "Embedded sub-expressions") — every other mocked construct gets `"commented_and_mocked"`.
Plus run-level metadata: resolved copybooks (path + occurrence count), any missing-copybook placeholders, cycle errors, anchor failures, synthesized WORKING-STORAGE items, and (after `build`) the raw `cobc` compiler output. `report.txt` is a human-readable rendering of the same data, grouped by paragraph, for quick manual review. `detect` mode prints an abbreviated version of this table directly to the terminal without writing files.

---

## 8. Implementation Phases

| Phase | Objective | Key modules | Target fixture(s) | Definition of done | Primary risk |
|---|---|---|---|---|---|
| **0 — Scaffolding** | Package skeleton, pytest wiring, decide WSL execution model | `cli.py`, `pyproject.toml` | n/a | `cobol_transform --help` runs inside WSL; one smoke test passes | Environment/tooling availability outside our control |
| **1 — Copybook inlining** | Text-level inliner correct on real + synthetic fixtures, no AST yet | `inline/*`, `discovery/copybook_resolver.py` | `lgstsq.cbl` (no copybooks, control case), then an `LGCMAREA`-copying program | `cobol_transform inline` produces expanded `.cbl` + `sourcemap.json`; unit-test matrix on comment/string/EXEC masking green | Fixed-format column edge cases |
| **2 — AST client + detection + anchoring** | End-to-end detection on the simplest real fixture; empirically resolve open node-type questions | `ast_client/*`, `analysis/node_classifier.py`, `analysis/anchor.py` | `lgstsq.cbl`, `lgucvs01.cbl` (for `CicsDFHRESPmacro`) | `cobol_transform detect` lists correct spans w/ correct line/col on both fixtures; document-order self-check passes | Confirms or falsifies the document-order anchoring assumption — deliberately scheduled early |
| **3 — CICS mock engine v1 + comment-preserving rewriter + EIB synthesis** | First fully compilable outputs, with original statements commented (not deleted) and terminators preserved | `analysis/symbol_table.py`, `analysis/exec_text_parser.py`, `mocks/rules_cics.py`, `mocks/rules_fallback.py`, `mocks/dummy_values.py`, `mocks/var_allocator.py`, `rewrite/terminator.py`, `rewrite/commenter.py`, `rewrite/rewriter.py` | `lgstsq.cbl`, `lgsetup.cbl` (breadth stress, 84 cmds), `lgwebst5.cbl` | Manual `cobc -x` succeeds on all three; output `.cbl` shows every mocked statement as a comment immediately above its mock; no `E-COMMENT-LINE-NOT-PURE`/terminator-mismatch diagnostics on any of the three | DFHRESP/EIB handling and terminator-preservation correctness — biggest known unknowns, budget explicit time |
| **4 — WSL compile/run harness + CLI/diagnostics** | Automated build+run+report | `compile/*`, `output/*`, remaining `cli.py` subcommands | Phase-3 fixtures | `cobol_transform build --run` compiles+runs one fixture end-to-end with JSON+text report | WSL path conventions — keep the project inside the WSL filesystem, not `/mnt/c/...` |
| **5 — VSAM + REDEFINES stress test** | Validate group/REDEFINES symbol-table handling and VSAM mock category | (existing modules, no new ones expected) | `lgucvs01.cbl`, `lgacvs01.cbl`, `lgdpvs01.cbl`, `lgicvs01.cbl`, `lgipvs01.cbl`, `LGCMAREA`-copying `*db01` family | All VSAM-touching fixtures compile+run | LINK-target COMMAREA mock fidelity — flagged for product-owner input |
| **6 — SQL rule set + REPLACING synthetic validation** | Full SQL coverage incl. cursors; validate REPLACING/nested-COPY on synthetic fixtures | `mocks/rules_sql.py`, `inline/replacing.py` (synthetic test hardening) | `lgicdb01.cbl`, `lgupdb01.cbl`, `lgipdb01.cbl` | Full 31-program corpus attempted; coverage matrix (compiled?/ran?/diagnostic count) produced | SQL mini-parser fragility — scope deliberately narrow, degrade to fallback rather than build a full SQL grammar |
| **7 — BMS/pseudo-conversational + hardening** | Full-corpus close-out | `SSMAP` inlining path, `RECEIVE MAP` field population reusing §6.3 | `lgtestc1.cbl`, `lgtestp1-4.cbl` | 31/31 (or documented exceptions) build; CI-ready suite | True pseudo-conversational multi-invocation semantics out of scope by design — document, don't chase |

---

## 9. Testing & Validation Plan

**Unit** (fast, no Java/WSL required): scanner exclusion rules (comment/string/EXEC masking, `OF`/`IN`, period-terminator disambiguation); `REPLACING` (identifier/literal/pseudo-text, synthetic fixtures); nested-COPY inliner (cycle detection, independent re-expansion of duplicate names); `SourceMap` offset lookup; `exec_text_parser` against literal strings taken directly from the real corpus (`LINK Program(LGACVS01) COMMAREA(DFHCOMMAREA) LENGTH(225)`, the `lgucvs01.cbl` READ/REWRITE strings); anchor algorithm against hand-constructed AST-shaped node lists including a deliberate duplicate-text case (proves correct sequencing) and a deliberate not-found case (proves fail-closed, not guess-and-continue); dummy-value table-driven tests; `var_allocator` collision suffixing; `symbol_table` PIC/`REDEFINES`/level-hierarchy reconstruction against a hand-built AST fragment resembling `LGCMAREA`'s 3-way/5-way nesting (no real AST call needed for this test).

**Unit — comment-preserving insertion & terminator handling** (new, §5.1/§5.2), all against hand-constructed offset ranges, no AST/Java needed:
- `terminator.py`: statement immediately followed by `.` + whitespace → `had_trailing_period=True`, range extended to include the period; statement immediately followed by another statement (no period, e.g. two CICS commands inside the same `IF` body as seen in `lgucvs01.cbl`) → `had_trailing_period=False`, range unchanged; a decimal point inside adjacent numeric text is never misread as a terminator (only reachable via whitespace-then-`.`-then-whitespace, per the algorithm, but tested explicitly as a regression guard).
- `commenter.py`: single-line statement → exactly one line gets column 7 forced to `*`; multi-line `EXEC CICS ... END-EXEC` spanning N lines (including a continuation line with indicator `-`) → all N lines commented, non-EXEC content elsewhere untouched; a synthetic case with live code sharing a line with the matched span → rejected with `E-COMMENT-LINE-NOT-PURE`, node skipped, not corrupted (proves the line-purity check, §5.1 step 2).
- `codegen.py` terminator matching: given `had_trailing_period=True`, generated mock's last line ends with `.`; given `False`, it does not — asserted for both a single-statement and a multi-statement mock rule.
- `rewriter.py`: original text for a mocked range is present in the output as a commented block (not deleted), located immediately above its generated mock, in document order matching the input.

**Integration** (`@pytest.mark.needs_java`, skippable without Java 21/LSP running): one full-pipeline test per complexity tier — `lgstsq.cbl`, `lgsetup.cbl`/`lgwebst5.cbl`, `lgicdb01.cbl`, `lgucvs01.cbl`, `lgipdb01.cbl`/`lgupdb01.cbl`, `lgtestc1.cbl` — each asserting zero unreplaced unsupported nodes, zero anchor errors, and structural sanity (paragraph/section counts and non-replaced-statement text unchanged vs. the original).

**Golden-file** (`tests/fixtures/golden/`): `lgstsq.cbl` and `lgucvs01.cbl` first (small enough to hand-review fully) — diff transformed output + manifest against checked-in expected artifacts. Introduced only once Phase 3/5 mock-text formatting has stabilized, to avoid churn on every codegen tweak.

**GNUCOBOL smoke tests** (`@pytest.mark.needs_wsl`, run less frequently): `build --run` for every integration-tier fixture, asserting `cobc` exit code 0 and, where deterministic, expected `>>> MOCK ...` trace lines in stdout; one deliberate negative test (hand-corrupted input) confirming compiler errors surface through the harness rather than being swallowed.

**Acceptance criteria for "done"**: all 31 GenApp programs run through `transform` produce output that `cobc` compiles with exit code 0; the manifest for each shows zero `skipped_anchor_error` entries; golden-file tests pass for the two curated small fixtures; unit test suite is green with no `needs_java`/`needs_wsl` markers required.

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Java AST tool's document-order-of-`Children` assumption turns out false on some construct | Phase 2's defensive self-check catches it immediately; documented fallback (assignment-based matching over `re.finditer` occurrences) is scoped but not built unless triggered |
| CICS/SQL mini-parser can't handle an option syntax variant | Falls through to `GenericFallbackRule` — always compiles, always safe, just less semantically rich; never blocks the pipeline |
| Copybook `REPLACING`/nested-COPY logic is unvalidated against real data (none in corpus) | Explicit synthetic fixture suite in Phase 1, called out as residual risk rather than assumed correct |
| LINK-target COMMAREA mock fidelity is fundamentally unknowable in general | Safe no-op default + convention-based success-field detection; explicitly flagged as needing product-owner input for higher fidelity, not silently guessed |
| Cursor-loop mocks (FETCH) could infinite-loop a `PERFORM UNTIL SQLCODE = 100` | Per-cursor call counter forces `SQLCODE = 100` after a configurable row count (default: after 1st FETCH) |
| WSL/Windows path handling bugs | Recommend running the whole pipeline (Python + Java tool + `cobc`) inside WSL, project checked out on the WSL filesystem, not `/mnt/c/...` |
| Large AST payloads (2.4MB/program) across 31 programs strain memory/CI time | HTTP server reuse avoids repeated JVM boot; `AstDocument` walk is a single streaming DFS, no need to hold multiple full ASTs simultaneously |
| Commenting a physical line could silently comment out unrelated live code sharing that line | `commenter.py`'s line-purity check (§5.1 step 2) fail-closes (`E-COMMENT-LINE-NOT-PURE`, skip) rather than commenting; validated as a non-issue on `genapp-files\src` specifically (§1.4), not assumed for other corpora |
| Inserting a mock with the wrong terminator (period present/absent) silently changes sentence/scope boundaries, altering control flow inside `IF`/`PERFORM` bodies | `rewrite/terminator.py` structurally detects the original's terminator presence and `codegen.py` reproduces it exactly on the mock (§5.2) — dedicated unit tests cover both cases from real corpus patterns |

---

## 11. Open Questions & Recommended Defaults

1. **Where does the pipeline run — WSL-native or Windows-host-calling-WSL?** *Default: entirely inside WSL* (Python, Java AST tool, `cobc` co-located) — avoids all cross-boundary path translation, and `cobc` must run in WSL regardless.
2. **Exact AST node type for native file I/O (OPEN/READ/WRITE/CLOSE/etc.) and confirmation that `CicsDFHRESPmacro` is the only DFHRESP-shaped node.** *Default: reserve predicate slots now, confirm empirically in Phase 2 against a fixture with real `FILE-CONTROL`/`FD`* (none exist in the current corpus, so this is untestable until such a fixture is supplied or synthesized).
3. **LINK-target COMMAREA mock fidelity** (generic no-op vs. per-target "realistic" response). *Default: no-op + trace `DISPLAY`, with an opt-in convention-based success-field write* — flagged for product-owner input if higher fidelity is needed later.
4. **`COPY ... OF/IN <library>` directory-mapping convention.** *Default: best-effort optional subdirectory hint*, no real corpus example to validate against.
5. **Whether every `OPEN`/`READ`/`WRITE` should be mocked, or only ones touching genuinely unavailable resources.** *Default: mock only CICS-mediated or native-file-I/O statements — i.e., anything the AST tool cannot itself run under plain GNUCOBOL. Ordinary in-memory `MOVE`/`COMPUTE`/data manipulation is never touched.* Since this corpus has zero native file I/O, in practice this defaults to "every CICS/SQL `ExecEndExec`, nothing else."
6. **Required GNUCOBOL version/flags.** *Default: target a current GnuCOBOL 3.x (`cobc -x -free`-or-fixed as appropriate, matching the source's format) available via WSL package manager (`apt install gnucobol` or building `gnucobol3`)* — confirm exact version once Phase 4 runs a real compile.
7. **SQL/CICS success vs. failure path default.** *Default: always success (RESP/SQLCODE = 0)*, with `--rule-config` overrides for scripted negative-path testing, per §6.4.
8. **May generated code add declarations?** *Yes, but minimized* — only EIB synthesis and rare scratch fields, always appended to `WORKING-STORAGE SECTION` under a clearly marked banner comment, never touching existing declarations (§6.5).

---

## 12. Final Prioritized Task Breakdown

1. Scaffold `cobol_transform` package + pytest + decide/document WSL execution model (Phase 0).
2. Build lexical masking + COPY/INCLUDE scanner + resolver + recursive inliner + source map; validate against `lgstsq.cbl` and one `LGCMAREA`-copying program (Phase 1).
3. Build synthetic `REPLACING`/nested-copy/cycle fixtures and their unit tests (parallel to step 2).
4. Wire `AstClient` against the HTTP server; build `AstDocument.walk()`; implement `node_classifier` + `anchor.py`; validate detection end-to-end on `lgstsq.cbl` and `lgucvs01.cbl`, resolving the DFHRESP/file-I/O node-type open questions (Phase 2).
5. Build `symbol_table.py` + `pic_parser.py` from real AST data (`LGCMAREA` REDEFINES as the stress case).
6. Build `exec_text_parser.py` (CICS side first) + `dummy_values.py` + `var_allocator.py` + `codegen.py`.
7. Build `rules_cics.py` (priority order: LINK, RETURN, ABEND, RESP-bearing verbs, counters, TSQ, ASKTIME/FORMATTIME, VSAM READ/WRITE/REWRITE/DELETE) + `rules_fallback.py` + `rules_eib.py`; wire `rewrite/rewriter.py` + `ws_injector.py` (Phase 3).
8. Build `compile/wsl_bridge.py` + `gnucobol_runner.py` + `output/manifest.py`/`writer.py`; complete `cli.py` subcommands (Phase 4).
9. Extend fixtures to full VSAM family + `LGCMAREA`-heavy `*db01` programs; harden symbol table against 5-way REDEFINES (Phase 5).
10. Build `exec_text_parser.py` SQL extractors + `rules_sql.py` (INSERT/SELECT/UPDATE/DELETE, then cursor lifecycle with loop-termination guard); run full 31-program coverage matrix (Phase 6).
11. Add BMS/`SSMAP` inlining + `RECEIVE MAP` field population; close out remaining menu-transaction fixtures (Phase 7).
12. Introduce golden-file tests once codegen stabilizes; finalize GNUCOBOL smoke-test suite and CI wiring.
