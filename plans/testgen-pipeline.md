# Plan: COBOL Test-Case Generation, Instrumentation & Coverage Pipeline

## Context

`cobol_transformer` already turns any COBOL/CICS program into a locally-runnable
GnuCOBOL program (`transformed/*.cbl`), driven through WSL via
`gnucobol/gnucobol_runner.py`. The transformed programs take no CLI args and no
stdin — all CICS pseudo-state (EIB fields, commarea) is synthesized as static
`WORKING-STORAGE VALUE` clauses, and mocked EXEC CICS/SQL calls return
deterministic, seed-free dummy data. So a transformed program's entire behavior
is a pure function of its `WORKING-STORAGE` initial state.

The next need is a **test-case + instrumentation + coverage pipeline** on top
of these transformed programs:

1. For each transformed program, generate several `testN.json` files (initial
   variable values + variables to check at the end), aimed at driving line and
   branch coverage as high as possible across the suite as a whole.
2. Instrument the program per test case: inject the initial-value `MOVE`s at
   the top, inject coverage probes at block/branch entry points, and inject an
   end-of-run check that reports actual vs. expected values.
3. Compile+run each instrumented variant and produce a report JSON with
   variable match/mismatch results and line/branch coverage.
4. Solve the "Claude can't know the real final values" problem with a
   deterministic oracle: **Claude never invents expected values.** It only
   picks initial values and *which* variables matter. A real GnuCOBOL
   execution (the oracle run) supplies the ground-truth expected values,
   which are then frozen into the test JSON.

This plan was built after reading, in depth: `pipeline.py`, `cli.py`,
`gnucobol/gnucobol_runner.py`, `ast_client/ast_model.py`,
`ast_client/http_client.py`, `analysis/symbol_table.py`,
`analysis/pic_parser.py`, `analysis/anchor.py`, `linetools.py`,
`mocks/codegen.py`, `rewrite/*`, and a real transformed program
(`transformed/lgtestp1.cbl`) end to end.

Two facts from that reading shape every design decision below:

- **AST line numbers are never trustworthy** (`stmtStartLineNumber` drifts,
  sometimes `end < start`). The only trustworthy AST signal is verbatim
  `Source Text`, located in the canonical text by forward search from a
  monotonically advancing cursor (`analysis/anchor.py::anchor_nodes`). Any new
  code that locates AST nodes in source text must follow this exact pattern.
- **All existing rewriting is pure text splicing on offsets**, never
  AST-regeneration (`rewrite/rewriter.py`, `rewrite/ws_injector.py`). New
  tooling should follow the same model.

A real transformed program (`transformed/lgtestp1.cbl`) confirms the shape to
design around: `SECTION`-based control flow with `GO TO` between sections
(not just `PERFORM`), `EVALUATE`/`WHEN` in several paragraphs, and **multiple
`GOBACK` exit points** scattered through different paragraphs (lines 1096,
1104, 1118, 1134 in that file alone) rather than one at the very end.

## Non-goals for v1 (explicit scope cut, confirmed with user)

- **EVALUATE/WHEN and PERFORM UNTIL/VARYING/TIMES branch coverage are phase 2.**
  The sample AST (`ast/out.json`) had no `EVALUATE` or non-trivial `PERFORM`,
  so those node/property names are unverified. v1 targets **paragraph/section
  entry coverage** (line-coverage proxy) and **IF/ELSE branch coverage** only,
  both of which are confirmed against real AST output.
- No changes to the existing `cobol_transformer` transformation pipeline
  itself — this is new, additive tooling that consumes `transformed/*.cbl`
  as input.

## Architecture: five stages

```
transformed/*.cbl
      │
      ▼
[1] generate_testcases.py ──(claude CLI, headless)──▶ testsuites/<program>/testN.json
      │                                                 (initial_values + variables_to_check only)
      ▼
[2] cfg.py (variable + control-flow extraction, reused by 3 & 4)
      │
      ▼
[3] instrumenter.py --mode oracle ─▶ instrumented/<program>/oracle/testN.cbl
      │
      ▼
[4] oracle_runner.py ──(compile+run via GnuCobolRunner)──▶ fills expected_values
      │                                                     into testsuites/<program>/testN.json
      ▼
[3] instrumenter.py --mode checked ─▶ instrumented/<program>/checked/testN.cbl
      │                                (init MOVEs + coverage probes + end-of-run CHK display)
      ▼
[5] run_and_report.py ──(compile+run)──▶ reports/<program>/testN.report.json
      │                                   reports/<program>/suite_summary.json
      ▼
   done
```

Stages 3+4 run once per test case to "bless" it (produce the frozen
`expected_values`). Stage 3(checked)+5 are the repeatable regression/coverage
run, re-runnable any time without touching Claude or the oracle again.

## New code location

New subpackage: `cobol_transformer/testgen/`, following the existing
package's module-per-concern convention. It imports `analysis.symbol_table`,
`analysis.pic_parser`, `analysis.anchor`, `ast_client`, `linetools`, and
`gnucobol.gnucobol_runner` directly — no duplication of existing logic.

```
cobol_transformer/testgen/
    __init__.py
    variable_context.py     # wraps symbol_table.py + pic_parser.py for prompt grounding
    prompt_builder.py        # builds the test-generation prompt (see below)
    generate_testcases.py    # CLI: loops a dir of .cbl, invokes `claude` headlessly
    cfg.py                   # paragraph/section + IF/ELSE extraction, block-ID assignment
    literal_format.py        # PicInfo -> COBOL literal text (shared by init + check codegen)
    instrumenter.py          # oracle-mode and checked-mode .cbl generation
    oracle_runner.py         # CLI: runs oracle .cbl, fills expected_values into testN.json
    run_and_report.py        # CLI: runs checked .cbl, parses TC: lines, writes report JSON
testsuites/<program>/testN.json          # test cases (generated, then frozen)
testsuites/<program>/coverage_manifest.json  # block_id -> {kind, paragraph, line range}
instrumented/<program>/oracle/testN.cbl
instrumented/<program>/checked/testN.cbl
reports/<program>/testN.report.json
reports/<program>/suite_summary.json
```

## Data schemas

**`testsuites/<program>/testN.json`** (final, frozen form):
```json
{
  "test_id": "test1",
  "program": "lgtestp1",
  "description": "drives EIBCALEN > 0 true branch, routes through A-GAIN, hits NO-ADD WHEN 70",
  "initial_values": {
    "EIBCALEN": "9999",
    "CA-RETURN-CODE": "70"
  },
  "variables_to_check": ["ERP1FLDO", "CA-RETURN-CODE"],
  "expected_values": {
    "ERP1FLDO": "Customer does not exist",
    "CA-RETURN-CODE": "70"
  },
  "generated_by": "claude+oracle",
  "generated_at": "2026-08-31T00:00:00Z",
  "oracle_source": "instrumented/lgtestp1/oracle/test1.cbl"
}
```
`expected_values` is absent/null until stage 4 (oracle) fills it in; the file
is not considered "frozen"/usable for stage 5 until it is populated.

**`testsuites/<program>/coverage_manifest.json`** — the block/branch
inventory built once per program by `cfg.py` (denominator for coverage %):
```json
{
  "program": "lgtestp1",
  "blocks": [
    {"id": "PARA-MAINLINE", "kind": "paragraph", "name": "MAINLINE",
     "line_start": 753, "line_end": 850},
    {"id": "IF-0007-THEN", "kind": "if-then", "paragraph": "MAINLINE",
     "line_start": 755, "line_end": 756},
    {"id": "IF-0007-ELSE", "kind": "if-else", "paragraph": "MAINLINE", ...}
  ]
}
```
IF blocks without an `ELSE` clause contribute only a `-THEN` entry (no
fabricated `-ELSE` block in v1 — see Open Risks).

**`reports/<program>/testN.report.json`**:
```json
{
  "test_id": "test1", "program": "lgtestp1",
  "compile_ok": true, "run_ok": true, "returncode": 0,
  "variables": {
    "ERP1FLDO": {"expected": "Customer does not exist", "actual": "Customer does not exist", "match": true},
    "CA-RETURN-CODE": {"expected": "70", "actual": "70", "match": true}
  },
  "all_match": true,
  "coverage": {
    "blocks_hit": ["PARA-MAINLINE", "IF-0007-THEN", "PARA-NO-ADD"],
    "blocks_total": 42,
    "block_coverage_pct": 7.1
  }
}
```

**`reports/<program>/suite_summary.json`** — union of `blocks_hit` across all
`testN.report.json` for that program, plus pass/fail counts per test.

## Component design

### 1. `variable_context.py` — grounding data for the prompt

Wraps `analysis.symbol_table.build_symbol_table(text)`. Emits, per elementary
(PIC-bearing, non-`FILLER`, non-88-level) symbol: `name`, `pic_text`,
`analysis.pic_parser.parse_picture(pic_text)` category/length/decimals/signed,
`section` (WORKING-STORAGE/LINKAGE-promoted/etc.), and its `VALUE` clause
default if any. This becomes a JSON block embedded in the prompt so Claude
never has to guess a variable name or emit a type-incompatible literal — it
picks only from this list.

Also extracts the paragraph/section list using the same regex approach
`pipeline.py` already uses internally (`_PARAGRAPH`), so Claude sees the
program's structural skeleton (paragraph names, order) without needing full
control-flow understanding — the actual branch enumeration for coverage
*targeting* is left to Claude reading the source directly (it reads the whole
`.cbl` file, which is small enough), while `cfg.py` independently computes the
ground-truth block list used for coverage *scoring* later. These two are
deliberately decoupled: Claude's job is to pick good inputs; `cfg.py`'s job is
to know, after the fact, exactly which blocks exist and which fired.

### 2. `prompt_builder.py` + `generate_testcases.py`

**Prompt** (drafted here in full since the user asked to see it; final
wording will be refined during implementation but this is the structure and
content to build from):

```
You are generating black-box test cases for a COBOL program that has already
been made locally runnable. The program takes no command-line arguments and
no stdin — its entire behavior is determined by the initial values of its
WORKING-STORAGE variables (including synthesized EIB/commarea fields), since
all external CICS/SQL calls have been replaced with deterministic mocks.

Your job has two parts:
1. Pick a diverse set of initial values for variables that influence control
   flow (IF conditions, EVALUATE subjects, loop conditions, GO TO routing
   fields such as EIBCALEN/CA-RETURN-CODE-style fields).
2. Pick which variables are worth checking at the end of execution — output
   fields, computed totals, status/return-code fields, error-message fields —
   whose final value meaningfully reflects that the right code path ran.

Do NOT attempt to compute or guess the final values of the variables you
choose to check. You do not have a COBOL interpreter and cannot reliably
trace CICS/SQL mock substitution rules by hand — a separate deterministic
step will execute the real program and capture the actual final values. Your
only job is to pick *which* variables are worth checking, not what their
values will be.

You will produce MULTIPLE test cases for this ONE program, because a single
test case can only exercise one path through the code. Your goal, across all
the test cases you write TOGETHER, is to maximize line and branch coverage:
every paragraph/section should be entered by at least one test, and every
IF/ELSE branch you can identify should be taken by at least one test in
either direction.

## Program source
<full text of transformed/<program>.cbl>

## Available variables (only choose from this list; do not invent names)
<JSON from variable_context.py: name, pic category, length, decimals, signed,
 section, default VALUE>

## Program structure (paragraph/section names, in order)
<list from variable_context.py>

## Instructions
1. Read the program and identify every decision point: each IF (note whether
   it has an ELSE), each EVALUATE and its WHEN clauses, each PERFORM
   UNTIL/VARYING/TIMES loop, and each GO TO-based routing (e.g. a field like
   EIBCALEN that decides which section is entered first).
2. Design the SMALLEST set of test cases such that, considered together,
   every decision point you found is exercised in as many of its distinct
   outcomes as you can drive purely by choosing initial WORKING-STORAGE
   values (aim for both true/false of every IF with an ELSE; if a decision
   depends on a field this program does not initialize under your control,
   note that and skip it rather than guessing).
3. Include boundary and edge-case values where relevant to a condition seen
   in the source (e.g. a field compared with `> 0`, `= SPACES`, a specific
   literal) — not just "typical" values.
4. For each test case, write a one-sentence `description` naming which
   decision point(s) or path it is meant to exercise.
5. For each test case, choose 1 or more `variables_to_check` whose final
   value would visibly differ depending on whether that decision point took
   the intended path (e.g. an error-message field only set in one branch).
6. Only use variable names and value shapes that are legal for that
   variable's PIC clause, from the "Available variables" list above (right
   length, numeric vs alphanumeric, sign if applicable).

## Output
Write one file per test case to <testsuites_dir>/<program>/test<N>.json
(test1.json, test2.json, ...), each shaped exactly as:
{
  "test_id": "test<N>",
  "program": "<program>",
  "description": "<one sentence>",
  "initial_values": {"<VAR>": "<value>", ...},
  "variables_to_check": ["<VAR>", ...]
}
Do NOT include an "expected_values" key — that is filled in later by a
separate deterministic step. Write only the JSON files; do not modify the
COBOL source.
```

**`generate_testcases.py`** (CLI):
```
python -m cobol_transformer.testgen.generate_testcases <transformed_dir> \
    [--out testsuites] [--claude-bin claude] [--force]
```
Loops `*.cbl` in `transformed_dir` sequentially (per user's choice — headless,
one program at a time to start). For each: builds the prompt via
`prompt_builder.py`, invokes `claude` non-interactively
(`subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits",
"--add-dir", str(out_dir/program)], cwd=repo_root, capture_output=True)`),
scoped so file writes land only under that program's `testsuites/<program>/`
directory. Logs how many `testN.json` files were produced per program, skips
programs that already have test files unless `--force`. Exact CLI flags for
the `claude` binary (permission mode, `--add-dir` scoping) will be confirmed
against the installed CLI version during implementation — the mechanism
(headless prompt in, JSON files out, one subprocess per program) is fixed.

### 3. `cfg.py` — ground-truth block/branch extraction (v1: paragraphs + IF/ELSE)

Given the canonical `expanded_text` (via `Inliner.inline_file` — copybooks
must be expanded first, same as the main pipeline) and its `AstDocument`
(via `HttpAstClient.get_ast`, same server the main pipeline already talks to
at `http://127.0.0.1:4010`):

1. **Paragraphs/sections**: walk the AST for `Paragraph0` and
   `SectionHeaderParagraph`/`SectionHeader0` nodes (confirmed present in the
   sample AST, carrying `properties._ParagraphName` /
   `properties._SectionName`). For each, locate its header line via verbatim
   `Source Text` search using the exact `anchor_nodes`-style forward-cursor
   technique (new code, but same algorithm as `analysis/anchor.py`) to get
   its start offset, and derive `line_end` as the offset just before the next
   paragraph/section header (or `PROCEDURE DIVISION` end). Emit one
   `{"id": "PARA-<NAME>", "kind": "paragraph", ...}` block per paragraph
   **and** section (a `SECTION` header is itself a valid PERFORM/GO TO
   target, as seen in `lgtestp1.cbl`'s `MAINLINE SECTION.`).
2. **IF/ELSE**: walk `IfStatement` nodes (confirmed present, with
   `_Condition`, `_StatementNextSentence` for the then-body, and an `_EndIf`
   property when scope-terminated). Locate the `IF` keyword offset and the
   `ELSE` keyword offset (if present) by verbatim search within the node's
   own `Source Text` span (not a fresh document-wide search — the whole
   `IfStatement.source_text` already contains "IF ... [ELSE ...] [END-IF]",
   so keyword offsets are found by scanning within that substring, then
   mapped back to the absolute document offset via the outer anchor). Emit
   `IF-<seq>-THEN` always, `IF-<seq>-ELSE` only when an `ELSE` exists.
3. Number blocks deterministically (`IF-0001`, `IF-0002`, ... in document
   order) so `coverage_manifest.json` is stable/diffable across regenerations
   of the same program.

Output: `CoverageManifest` dataclass + `write coverage_manifest.json`.

**Before implementing IF/ELSE extraction**, run the AST HTTP server against
one program confirmed to contain `ELSE` (need to grep `genapp-files/src/*.cbl`
for one — `lgtestp1.cbl`'s sample only showed IF without ELSE in the excerpt
read) to confirm the exact `Children`/property shape for the else-branch
before finalizing the offset-finding code. Small, cheap verification step,
not a redesign risk.

### 4. `literal_format.py`

`pic_info_to_move_literal(pic: PicInfo, value: str) -> str` and
`pic_info_to_condition_literal(pic: PicInfo, value: str) -> str` (same
formatting, exposed separately for readability at call sites): alphanumeric →
`cobol_string_literal(value)` (reuse `mocks/codegen.py::cobol_string_literal`
directly); numeric → the digit string as-is, with a literal decimal point
when `pic.decimals > 0` (COBOL numeric literals accept `123.45` directly, no
V-to-decimal conversion needed); reject/flag values that don't fit
`pic.length`/`pic.digits`/`pic.decimals` up front rather than emitting
invalid COBOL.

### 5. `instrumenter.py` — insertion-only instrumentation

**Key design win**: unlike the existing `mocks`/`rewrite` machinery — which
*replaces* statements in place and therefore has to carefully preserve
sentence-terminating periods (`rewrite/terminator.py`) — this instrumenter
only ever **inserts brand-new, self-contained statements immediately before
or after an existing complete-statement boundary**. It never touches an
existing statement's own terminator. Every inserted statement (`DISPLAY
'TC:...'`, `MOVE ... TO ...`, `PERFORM ZZ-...`) is written as its own
complete sentence with its own period, which is always syntactically legal
immediately before/after another complete statement — so none of
`rewrite/terminator.py`'s scope-tracking logic is needed here. This
significantly simplifies the instrumenter relative to the mock-rewriting
pipeline. No new `WORKING-STORAGE` fields are needed either (unlike
`rewrite/ws_injector.py`): initial values and expected values are written as
literal operands directly in generated `MOVE`/`IF` statements, so this
instrumenter only ever inserts into the `PROCEDURE DIVISION`.

**Common structure for both modes**, built as text-offset insertions (list of
`(offset, inserted_text)` applied bottom-up so earlier offsets stay valid —
same pattern as `ws_injector.py`'s `lines[pos:pos] = payload`):

- **Init block**: a new paragraph `ZZ-TESTCASE-INIT.` containing one `MOVE
  <literal> TO <VAR>.` per `initial_values` entry (via `literal_format.py`),
  formatted through `mocks/codegen.py::render_statements`. Inserted as the
  very first paragraph, immediately after the `PROCEDURE DIVISION.` header
  and before the program's existing first paragraph/section header, together
  with a `PERFORM ZZ-TESTCASE-INIT.` as the literal first statement of the
  original first paragraph. (Implementation spike: confirm GnuCOBOL accepts
  a named paragraph inserted before a program's first `SECTION` header in a
  `SECTION`-structured `PROCEDURE DIVISION` — expected to be fine since
  paragraphs may exist before the first `SECTION`, but verify by compiling
  one instrumented `lgtestp1.cbl` early.)
- **Exit points**: text-search the `PROCEDURE DIVISION` for every `GOBACK`
  and `STOP RUN` statement (confirmed multiple per program from
  `lgtestp1.cbl`: 4 separate `GOBACK`s). Immediately before each, insert
  `PERFORM ZZ-TESTCASE-CHECK.` (checked mode) or `PERFORM ZZ-TESTCASE-DUMP.`
  (oracle mode) as its own complete statement.
- **New trailer paragraph** (`ZZ-TESTCASE-DUMP` or `ZZ-TESTCASE-CHECK`)
  appended after the last existing paragraph, containing the mode-specific
  body below, followed by `ZZ-TESTCASE-INIT`'s own `EXIT.`/fallthrough
  handled the same way any appended paragraph is.

**Oracle mode body** (`ZZ-TESTCASE-DUMP`), one line per `variables_to_check`
entry:
```cobol
           DISPLAY 'TC:DUMP:<VAR>=' <VAR>.
```

**Checked mode body** (`ZZ-TESTCASE-CHECK`), one `IF`/`ELSE` per
`variables_to_check` entry, using the frozen `expected_values` as a literal
condition operand (no synthesized fields needed):
```cobol
           IF <VAR> = <expected-literal>
               DISPLAY 'TC:CHK:<VAR>:EXPECTED=<expected-literal-text>:ACTUAL=' <VAR> ':MATCH=Y'
           ELSE
               DISPLAY 'TC:CHK:<VAR>:EXPECTED=<expected-literal-text>:ACTUAL=' <VAR> ':MATCH=N'
           END-IF.
```

**Coverage probes** (checked mode only, driven by `coverage_manifest.json`):
- Paragraph/section block: insert `DISPLAY 'TC:COV:<block-id>'.` as the
  literal first statement of that paragraph/section (after
  `ZZ-TESTCASE-INIT`'s own probe/perform, for the very first paragraph).
- IF-THEN block: insert `DISPLAY 'TC:COV:<block-id>'.` as the first statement
  immediately after the `IF <condition>` line, before the branch's original
  first statement.
- IF-ELSE block: same, immediately after the `ELSE` keyword.

All coverage probes are single self-contained literal `DISPLAY` statements —
no variables involved, so no PIC/type concerns, and (per the insertion-only
argument above) no terminator concerns either, since they are always inserted
as an *additional* statement before the branch's existing first statement,
never touching the branch's own closing period.

`instrumenter.py` writes both the `.cbl` and a small per-instrumentation
manifest (`instrumented/<program>/{oracle,checked}/testN.manifest.json`)
recording exactly which block IDs and variable names were instrumented, so
stage 5's parser doesn't have to re-derive it from the `.cbl` text.

### 6. `oracle_runner.py`

```
python -m cobol_transformer.testgen.oracle_runner <testsuites_dir>/<program> \
    [--transformed-dir transformed] [--gnucobol-flags ...] [--force]
```
For each `testN.json` in the program's test dir lacking `expected_values` (or
all, with `--force`): calls `instrumenter.instrument(mode="oracle", ...)`,
`GnuCobolRunner().compile(...)` then `.run(...)` (reusing the existing
runner exactly as `cli.py cmd_build --run` does), parses stdout lines
matching `^TC:DUMP:(?P<var>[^=]+)=(?P<val>.*)$`, writes the captured values
back into `testN.json` as `expected_values`, and fails loudly (non-zero exit,
diagnostic printed) if compile or run failed — a test case whose oracle
couldn't run is never silently left without `expected_values`.

### 7. `run_and_report.py`

```
python -m cobol_transformer.testgen.run_and_report <testsuites_dir>/<program> \
    [--transformed-dir transformed] [--out reports]
```
For each frozen `testN.json`: `instrumenter.instrument(mode="checked", ...)`,
compile+run via `GnuCobolRunner`, parse stdout for `^TC:COV:(?P<id>.*)$` and
`^TC:CHK:(?P<var>[^:]+):EXPECTED=(?P<exp>.*?):ACTUAL=(?P<act>.*?):MATCH=(?P<m>[YN])$`,
cross-reference hit block IDs against `coverage_manifest.json`'s full block
list to compute `block_coverage_pct` (and a `line_coverage_pct` derived from
summing `line_end - line_start + 1` of hit blocks vs. total instrumentable
lines, as a coverage proxy — true line coverage would need a probe per line,
which the user explicitly asked to avoid for scalability). Writes
`testN.report.json`. After all tests for a program: writes
`suite_summary.json` with the **union** of `blocks_hit` across every test
(this is the number that matters — the whole point of multiple test cases is
suite-level coverage, not any single test's coverage) plus a pass/fail table.

## Phased delivery

1. **Phase 0 — spikes (half day)**: (a) confirm a named paragraph can be
   inserted before a program's first `SECTION` header and still compile/run
   correctly under GnuCOBOL/WSL; (b) confirm the AST's `IfStatement`
   shape for a program that actually has an `ELSE` clause (grep
   `genapp-files/src/*.cbl` for one first).
2. **Phase 1 — MVP, one program end to end**: build `variable_context.py`,
   `cfg.py` (paragraphs/sections + IF/ELSE only), `literal_format.py`,
   `instrumenter.py`, `oracle_runner.py`, `run_and_report.py`. Hand-write 2-3
   test JSON files for `lgtestp1.cbl` (skip `generate_testcases.py`/Claude
   for this phase) to validate the instrument → oracle → check → report loop
   compiles, runs, and produces sane coverage numbers.
3. **Phase 2 — Claude-driven generation**: build `prompt_builder.py` +
   `generate_testcases.py`, run it against `lgtestp1.cbl`, sanity-check the
   generated test cases by eye, then run the full oracle→check→report loop
   on Claude-generated tests.
4. **Phase 3 — scale out**: run the full pipeline (generate → oracle → check
   → report) across all 10 `transformed/*.cbl` programs; add EVALUATE/WHEN
   branch coverage now that IF/ELSE proved the pattern out.

## Open risks flagged for later (not blocking the plan, but worth knowing)

- **IFs without an `ELSE`**: v1 only reports a `-THEN` block for these, so
  "branch coverage" undercounts the false-path. A phase-2 enhancement is a
  join-point probe right after `END-IF`/the sentence period, inferring
  false-path coverage as "join fired AND then-probe did not."
- **`GO TO`-based routing** (seen in `lgtestp1.cbl`, e.g.
  `IF EIBCALEN > 0 GO TO A-GAIN.`) means paragraph-entry coverage can diverge
  from a naive top-to-bottom read of the source — this is exactly why
  block-based instrumentation (not line-based) was chosen, and why the IF
  branch above is itself one of the IF/ELSE blocks tracked.
- Stale goldens: if the underlying `cobol_transformer` transformation logic
  changes and a program's semantics shift, previously frozen
  `expected_values` become wrong. Regeneration is a deliberate re-run of
  `oracle_runner.py --force`, never automatic — same tradeoff as any golden
  master test suite.

## Verification

- Phase 1: manually inspect one instrumented `.cbl` for `lgtestp1`, confirm
  it compiles under WSL GnuCOBOL (`cobc -x -std=default`) and that a hand-run
  reproduces expected `TC:DUMP:`/`TC:COV:`/`TC:CHK:` lines.
- Phase 2: spot-check 2-3 Claude-generated test cases against the source by
  eye for plausibility (right variable names, right PIC-shaped values).
- Phase 3: run `run_and_report.py` across the full corpus and confirm
  `suite_summary.json` coverage numbers move up as more test cases are added
  for a program (sanity check that the union-coverage math is working).
