# Test-Case Generation, Instrumentation & Coverage (`testgen/`)

Modules: `variable_context.py`, `cfg.py`, `literal_format.py`,
`instrumenter.py`, `prompt_builder.py`, `generate_testcases.py`,
`oracle_runner.py`, `run_and_report.py`

This is a second pipeline, additive to the one documented in the rest of
`docs/`. It does not touch `cobol_transformer`'s transformation logic; it
consumes `transformed/*.cbl` as input and never modifies it.

## 1. The idea in one paragraph

A transformed program takes no command-line arguments and no stdin. Every
`EXEC CICS`/`EXEC SQL` call in it has already been replaced with a
deterministic, seed-free mock (see [Mock Generation](05-mocking.md)). That
means a transformed program's entire behaviour is a pure function of its
`WORKING-STORAGE` initial values — so a test case can be described completely
as "start with these values, and check that these variables end up like
this." The pipeline in this document generates such test cases, executes them
for real to get ground-truth answers, then instruments and re-runs them
repeatedly as a regression suite with line/branch coverage numbers, without
needing a model or a mainframe again.

## 2. Why expected values are never guessed

The one rule that shapes the whole design: **the model picks inputs, never
outcomes.**

A model can plausibly guess *at* what a mocked CICS/SQL substitution does, but
it cannot reliably hand-trace it — the mock rules are seed-dependent
(`--seed`), field-name-dependent (`mocks/dummy_values.py`), and interact with
whatever the program does to the result afterward. A wrong guess baked into a
test case as `expected_values` does not fail loudly; it makes a broken suite
report success forever, which is worse than having no suite at all.

So the model's job is narrowed to two things it *can* do reliably by reading
the source: choosing initial values that drive interesting control flow, and
naming which variables are worth inspecting afterward. A real execution of the
real (transformed) program supplies the only allowed source of truth for what
those variables end up holding. That execution is called **the oracle**, and
the values it produces are then frozen into the test case — after which the
test case never needs the model or the oracle again.

## 3. Architecture: five stages

```
transformed/<program>.cbl
        │
        ▼
[1] generate_testcases.py ──(claude, headless, stdin)──▶ testsuites/<program>/testN.json
        │                                                  (initial_values + variables_to_check only)
        ▼
[2] cfg.py  (paragraph/section + IF/ELSE block inventory, via the AST — reused by 3 & 5)
        │
        ▼
[3] instrumenter.py --mode oracle ──▶ instrumented/<program>/oracle/testN.cbl
        │
        ▼
[4] oracle_runner.py  (compile + run via GnuCobolRunner) ──▶ fills expected_values
        │                                                      into testsuites/<program>/testN.json
        ▼
[3] instrumenter.py --mode checked ──▶ instrumented/<program>/checked/testN.cbl
        │                               (init MOVEs + coverage probes + TC:CHK: comparison)
        ▼
[5] run_and_report.py  (compile + run) ──▶ reports/<program>/testN.report.json
        │                                   reports/<program>/suite_summary.json
        ▼
     done
```

Stage 1 (and stages 3+4, which "bless" a test case) run once, and cost a
`claude` invocation for stage 1 only. Stage 3(checked)+5 is the repeatable
part — re-runnable at any time with no AI and no fresh oracle run, exactly
like any regression suite built on golden files.

## 4. Module map

```
testgen/
  variable_context.py   grounding facts about a program's variables, for the prompt
  prompt_builder.py     builds the headless test-generation prompt
  generate_testcases.py CLI: stage 1 — drives `claude` per program, validates output
  cfg.py                CLI-free: stage [2] — paragraph/section + IF/ELSE block inventory
  literal_format.py     PicInfo + value -> legal COBOL literal, fixed-format layout
  instrumenter.py        stage [3] — oracle-mode and checked-mode .cbl generation
  oracle_runner.py      CLI: stage [4] — runs oracle .cbl, freezes expected_values
  run_and_report.py     CLI: stage [5] — runs checked .cbl, parses coverage + checks
testsuites/<program>/testN.json              test cases (generated, then frozen)
testsuites/<program>/coverage_manifest.json  block inventory (rewritten each run)
instrumented/<program>/{oracle,checked}/testN.cbl  + testN.manifest.json
reports/<program>/testN.report.json
reports/<program>/suite_summary.json
```

## 5. Data schemas

### `testsuites/<program>/testN.json` — a test case

Before stage 4 runs, `expected_values` is absent and the case is unusable by
stage 5 (`instrumenter.py` refuses to build a `checked`-mode source for it —
see §8). After stage 4:

```json
{
  "test_id": "test1",
  "program": "lgtestp1",
  "description": "EIBCALEN > 0 takes the IF-0001 true branch and routes straight to A-GAIN",
  "initial_values": {
    "EIBCALEN": "9999",
    "CA-RETURN-CODE": "70"
  },
  "variables_to_check": ["ERP1FLDO", "CA-RETURN-CODE"],
  "expected_values": {
    "ERP1FLDO": "Please enter a valid option",
    "CA-RETURN-CODE": "70"
  },
  "generated_by": "oracle",
  "generated_at": "2026-09-01T12:03:44Z",
  "oracle_source": "instrumented/lgtestp1/oracle/test1.cbl"
}
```

A test case with an empty `variables_to_check` is legal and is treated as
**frozen by definition** — it asserts nothing about values and exists only to
drive coverage, so there is nothing for the oracle to supply. Its `all_match`
in stage 5 is just whether the run completed.

### `testsuites/<program>/coverage_manifest.json` — the coverage denominator

Built once per program by `cfg.py` and rewritten at the top of every
`run_and_report.py` run, so it never drifts from the instrumented source:

```json
{
  "program": "lgtestp1",
  "procedure_lines": 421,
  "blocks": [
    {"id": "PARA-MAINLINE", "kind": "section", "name": "MAINLINE",
     "line_start": 753, "line_end": 775},
    {"id": "IF-0001-THEN", "kind": "if-then", "name": "IF-0001",
     "line_start": 756, "line_end": 756, "paragraph": "MAINLINE"}
  ]
}
```

An `IF` without an `ELSE` contributes only a `-THEN` block — no fabricated
`-ELSE` is invented (see §9, open risks).

### `reports/<program>/testN.report.json`

```json
{
  "test_id": "test1", "program": "lgtestp1",
  "compile_ok": true, "run_ok": true, "returncode": 0,
  "variables": {
    "ERP1FLDO": {"expected": "Please enter a valid option",
                 "actual": "Please enter a valid option", "match": true},
    "CA-RETURN-CODE": {"expected": "70", "actual": "70", "match": true}
  },
  "all_match": true,
  "coverage": {
    "blocks_hit": ["PARA-MAINLINE", "IF-0001-THEN", "PARA-A-GAIN", "PARA-ENDIT-STARTIT"],
    "blocks_total": 16, "block_coverage_pct": 25.0,
    "lines_covered": 341, "lines_total": 418, "line_coverage_pct": 81.6
  }
}
```

`reports/<program>/suite_summary.json` is the **union** of `blocks_hit` across
every test for that program — that union, not any single test's percentage,
is the number that matters, since the entire reason to write several test
cases is to cover more together than any one of them does alone.

## 6. Stage 1 — `generate_testcases.py` and the prompt

```bash
python -m cobol_transformer.testgen.generate_testcases transformed \
    [--out testsuites] [--claude-bin claude] [--min-tests 15] \
    [--program lgtestp1 ...] [--force] [--dry-run]
```

One `claude -p` subprocess per program, run sequentially. The prompt
(`prompt_builder.build_prompt`) embeds the full program source, a compact
one-line-per-field table of every settable `WORKING-STORAGE` variable (name,
PICTURE, category, length, decimals, signed, section, default value — from
`variable_context.py`), and the paragraph/section skeleton, so the model never
has to invent a variable name or a type-incompatible value. It is explicitly
told not to compute expected values, and to write `--min-tests` (default
**15**) cases per program — a floor, not a target: reaching every decision
point the model can actually influence usually takes far fewer, so it is told
to spend the rest on boundary values, the empty/SPACES/zero form of each
field a condition reads, and one representative per equivalence class of a
field compared against several literals, rather than on near-duplicates.

**The floor is enforced on the way out, not just requested in the prompt.**
`generate_for_program` counts the `testN.json` files actually written and
reports a shortfall as a failure (`only 9 test case(s) written, 15 required`),
which makes the CLI exit non-zero exactly like an invalid generated variable
name does.

**Validation before acceptance.** Every generated file is loaded and checked
against the program's real symbol table: an unknown variable name, a value
that will not fit its PICTURE, or a stray `expected_values` key (which the
model was told never to include) is rejected here with a specific message —
never allowed to surface later as a mysterious COBOL compile error inside
generated code.

**Access is scoped.** `claude` is invoked with `--add-dir` limited to that
program's own `testsuites/<program>/` directory, so a run cannot touch the
COBOL sources, another program's suite, or anything else in the repo.

**The prompt goes in over stdin, not argv.** A prompt embedding a whole
program plus its variable table runs to tens of kilobytes — one real run
against `lgtestp1.cbl` produced an 83 KB prompt. Passed as a `subprocess.run`
argv element that exceeds Windows' `CreateProcess` command-line limit
(32,767 characters) and fails immediately with `WinError 206`, before `claude`
even starts. `generate_testcases.py` instead runs `claude -p` with no prompt
argument and passes the prompt via `input=`, which has no such limit. This
was found by running the pipeline for real, not anticipated in advance — see
§10.

## 7. Stage 2 — `cfg.py`, the coverage denominator

`cfg.py` answers one question per program: which paragraphs/sections and
IF/ELSE branches exist, and at what exact text offset does each one begin? It
is the module the coverage percentages are computed against, and it is
deliberately decoupled from stage 1 — the model's job is to pick good inputs
by reading the source directly; `cfg.py`'s job is to know, independently and
after the fact, exactly which blocks exist and which fired.

v1 scope is **paragraph/section entry** (a line-coverage proxy) and
**IF-THEN/IF-ELSE** (branch coverage) only — confirmed against real AST
output from the corpus. `EVALUATE`/`WHEN` and `PERFORM UNTIL`/`VARYING`/`TIMES`
are out of scope for v1 (see §9).

### Why it cannot reuse `analysis.anchor`

[Anchoring](03-detection-and-anchoring.md) elsewhere in this codebase walks
the AST once with a single monotonically advancing cursor — correct for the
flat list of `EXEC` blocks it locates, because they never nest and the
serializer always emits them in document order.

Neither is true here. `IfStatement` nodes **nest** (an `ELSE` branch can
contain another `IfStatement`), so an inner node's text lies *inside* a span
the cursor has already advanced past. And the serializer emits grammar slots
**out of document order** — an `IfStatement`'s `EndIf` child appears in
`Children` before its `ELSE` token does, confirmed against a real
`cobc`-parsed `IfStatement` node (`lgtestp4.cbl`, which has real `ELSE`
clauses; the `lgtestp1`–`lgtestp3` family does not).

So `cfg.py` anchors **hierarchically**: each node is located within the text
span already established for its parent (`_anchor_tree`), with a retry from
the parent's own start when the first search fails, to tolerate the
out-of-order slots. `analysis.anchor`'s core discipline is preserved
regardless — **AST line numbers are never read**; every offset comes from a
verbatim `Source Text` search — this module just needed a different search
strategy to apply that discipline to a nested grammar.

### Getting probe placement right

A block's `probe_offset` is not simply where the AST says the construct
starts:

- A **paragraph/section** probe goes just past the period that ends its
  header (`_body_offset_after_header`) — so it counts as "entered", not
  merely "declared".
- An **IF-THEN** probe goes at the start of `_StatementNextSentence` (the
  AST's name for the then-body) — not at the `IF` keyword, which would fire
  regardless of which way the condition went.
- An **IF-ELSE** probe goes at the start of `_StatementNextSentence6` (the
  AST's name for the else-body, located from `then_at` onward) — only emitted
  when the node actually carries an `_ELSE` property.

Adjacent paragraph/section line ranges are snapped so they never share a
boundary line (`stop = index.line_start(...)`) — without that, the line-count
proxy would double-count the line a paragraph header shares with the end of
the previous paragraph.

A block whose then-body or condition cannot be located inside its own AST
span is **dropped with a `W-CFG-IF-NOT-LOCATED` diagnostic**, not probed at a
guessed offset — the same fail-closed discipline as `analysis.anchor`.

## 8. Stage 3 — `instrumenter.py`

Two modes over the same core mechanism:

| Mode | Adds | Used by |
|---|---|---|
| `oracle` | init `MOVE`s + a `DISPLAY 'TC:DUMP:<var>=' <var>` per checked variable at every exit | `oracle_runner.py`, to capture ground truth |
| `checked` | init `MOVE`s + a `DISPLAY 'TC:COV:<block-id>'` at every block + an `IF <var> = <expected> ... TC:CHK:...` comparison per checked variable | `run_and_report.py`, the repeatable suite |

`checked` mode requires a frozen test case — `instrument()` raises
`InstrumentError` if `expected_values` is still absent for a case that has
variables to check.

### Insertion-only, and why that is simpler than the mock rewriter

[The mock rewriter](06-rewriting.md) *replaces* statements in place, which is
why it needs `rewrite/terminator.py`'s careful scope tracking: a replaced
statement has to reproduce the terminator of what it replaced. This
instrumenter never replaces anything — it only ever **inserts** brand-new,
self-contained statements immediately before or after an existing
complete-statement boundary. Every inserted statement carries its own period
(or deliberately does not — see below), which is always syntactically legal
next to another complete statement, so none of the mock rewriter's
scope-tracking machinery is needed. No new `WORKING-STORAGE` fields are
needed either: initial and expected values are written as literal operands
directly in the generated `MOVE`/`IF` statements, so instrumentation only
ever touches the `PROCEDURE DIVISION`.

### The one place "insertion-only" is not actually simple: periods

The plan this module was built from claimed insertion-only meant "no
terminator concerns at all." That turned out to be wrong in one specific,
sharp way, discovered by compiling and running the result rather than
reasoning about it in the abstract:

```cobol
IF EIBCALEN > 0            IF EIBCALEN > 0
   GO TO A-GAIN.    -->       DISPLAY 'TC:COV:IF-0001-THEN'
                              GO TO A-GAIN.
```

A probe inserted here **with its own period** would close the `IF` sentence
right after the `DISPLAY`, leaving `GO TO A-GAIN.` to run **unconditionally**
— a change of behaviour that compiles cleanly and produces no error, only a
silently wrong branch. So a branch probe must join the surrounding sentence
and carry **no period**; only a probe that opens a fresh paragraph body — where
starting a new sentence is always legal — gets one.
`cfg.Block.probe_period` records which case each block is, and
`literal_format.render_harness_statement(..., period=...)` is the single
place that decides whether a period is appended. This is verified at
runtime, not just asserted: `tests/unit/test_testgen.py` compiles and runs a
program with `EIBCALEN = 0` and confirms `IF-0001-THEN`'s probe does **not**
fire, and, for a real IF/ELSE, that the two branches are never both reported
hit on the same run.

### Column-72 discipline: the other gotcha found by compiling

COBOL fixed format ends the code area at column 72. `literal_format.py`
lays out every generated statement to respect that — but the sharper rule,
found the same way (compile, don't assume), is about **continued literals**:
the *content* of a literal continued via a `-` in column 7 runs through
column 72 of the line it continues from. A line that stops one column short
of 72 does not truncate the value — it silently **pads it with spaces up to
column 72**, corrupting the literal in a way that still compiles and only
fails at comparison time. `render_harness_statement` therefore pads every
mid-literal line to *exactly* column 72
(`cur.ljust(MAX_COL)` at the split point), never short of it — proven with a
test that reconstructs a literal from rendered lines the way a fixed-format
compiler actually reads them, including the padding rule, and checks it
equals the original value for several values that force continuation.

### Literal construction is the ground truth's mirror image

`literal_format.pic_info_to_move_literal`/`pic_info_to_condition_literal`
turn an *observed* value (from `DISPLAY`) back into a *literal* a compiler
will accept — verified against real `cobc 3.1.2` output rather than assumed:

| PICTURE | `DISPLAY` renders | Literal used |
|---|---|---|
| `X(20)` | `hello` (space-padded) | `'hello'` (comparison space-pads the shorter side) |
| `9(4)` | `0070` | `0070` — leading zeros are legal in a numeric literal |
| `S9(4) COMP` | `-0005` | `-0005` |
| `S9(3)V99` | `+012.34` | `+012.34` — a real decimal point, no V-to-decimal conversion |
| `+9(5)` (numeric-edited) | `+00100` | compared as a **character** literal, `'+00100'` — see below |
| all spaces | `          ` | `SPACES` (`''` is not valid COBOL) |

Two of those rows are regressions found by running the checked-mode reports
across the full corpus and getting real, reproducible mismatches — not
findable from unit tests alone, because both fields are absent from every
hand-written or synthetic test fixture used earlier in development:

- **A numeric field that `DISPLAY`s as blanks was never initialised on that
  path.** `lgapdb01`'s `CA-POLICY-NUM` (`PIC 9(10)`) does this on several
  generated test cases. Asserting `= 0` against it — the MOVE-form treatment
  of an empty operand — produced a check that failed against the very run
  the "expected" value was captured from. `pic_info_to_condition_literal`
  now refuses to build a comparison for a blank numeric field
  (`LiteralError`), and the caller reports it as **not compared**, with the
  reason, rather than asserting a wrong literal that happens to compile.
- **A numeric-edited PICTURE's `length` counts digits, not columns.**
  `PIC +9(5)` (`lgicdb01`'s `EM-SQLRC`) parses to `length=5`, but the field
  occupies **six** print columns because of the sign, and `DISPLAY` duly
  renders `+00100`. Enforcing `length` as a character-width ceiling rejected
  the field's own legitimate value. The length guard is now skipped for
  `PicCategory.NUMERIC_EDITED`, which is instead compared as the character
  string `DISPLAY` produced.

Both are covered by regression tests naming the exact corpus field that
surfaced them (`test_blank_numeric_field_is_refused_not_asserted_as_zero`,
`test_numeric_edited_length_counts_columns_not_digits`).

## 9. Stages 4 & 5 — `oracle_runner.py` and `run_and_report.py`

```bash
python -m cobol_transformer.testgen.oracle_runner testsuites/lgtestp1 \
    [--transformed-dir transformed] [--force] [--keep-going]

python -m cobol_transformer.testgen.run_and_report testsuites/lgtestp1 \
    [--transformed-dir transformed] [--out reports]
```

Both compile and run through the existing `gnucobol.gnucobol_runner`
([CLI & Operations](09-cli-and-operations.md)) — no new compiler integration.
`oracle_runner.py` parses `^TC:DUMP:(?P<var>[^=]+)=(?P<val>.*)$` from stdout,
last-occurrence-wins (a program that both falls through to the trailer and
reaches an explicit exit would otherwise report a variable's value twice; the
final observation is the one that describes the end of the run), and refuses
to freeze a case that produced no value for one of its checked variables — a
test case whose oracle could not run is never left half-blessed with a
partial or invented golden.

### A gotcha specific to this corpus: exit code is not a verdict

Elsewhere in this codebase a non-zero `cobc`/program exit is a failure. It is
not here. `RETURN-CODE` is an ordinary `WORKING-STORAGE`-adjacent COBOL
special register the transformed programs write to as program state — and
one corpus program (`lgapdb01`, on several generated paths) leaves it holding
four ASCII spaces at exit, which the OS reports as exit code **32**
(`0x20202020` truncated), while the run itself completed **perfectly** and
emitted every `TC:DUMP:` line the oracle needed. Treating that exit code as
"the run failed" produced false failures across six otherwise-passing test
cases the first time the full corpus was run.

Both `oracle_runner.build_and_run` callers and `run_and_report.run_testcase`
therefore only treat a **negative** return code — meaning the runner's own
subprocess timed out rather than the program exiting on its own — as a
run failure. Any other exit code is recorded (`report["returncode"]`) but
never judged; what proves the run succeeded is the presence of the expected
`TC:DUMP:`/`TC:CHK:` output, not the process's own exit status.

### Coverage scoring

`run_and_report.coverage_report` computes block coverage as a straightforward
ratio of hit blocks to the manifest's total. Line coverage is a **proxy, and
a generous one** — true line coverage would need a probe on every line, which
does not scale to a 1000+ line program. Instead:

- covered lines are the **union** of hit blocks' line ranges (IF blocks nest
  inside their paragraph, so a union rather than a sum avoids double-counting
  those lines);
- **minus** the union of ranges belonging to blocks that did **not** fire —
  otherwise entering a long paragraph would silently credit every line of
  every branch body nested inside it, regardless of which branch actually
  ran. This subtraction was added after a first real run reported 84.4% line
  coverage against 25% block coverage on the same test suite, which is not a
  believable pairing.

Even with that correction, the number still reads high, because v1 (§7)
tracks no block for an `EVALUATE`/`WHEN` body, so those lines stay credited
to the enclosing paragraph regardless of which `WHEN` ran.
**Block coverage is the number to trust**; read the line figure as an upper
bound until `WHEN` branches get their own blocks.

`suite_summary.json`'s `suite_coverage` is the **union** of `blocks_hit`
across every test case for a program, plus a per-test pass/fail table — the
number that actually matters, since the whole reason to write more than one
test case is what the set covers together.

## 10. Running it for real: what changed from the written plan

The plan this pipeline was built from got the architecture right but missed
three things that only running it against real programs, a real `claude`
binary, and real GnuCOBOL surfaced:

1. **The `claude -p <prompt>` argv invocation is unusable on Windows** for a
   prompt this size (§6) — `WinError 206`, fixed by moving the prompt to
   stdin.
2. **A branch probe cannot carry its own period** (§8) — it would silently
   make a guarded `GO TO` unconditional. Caught by compiling and running an
   instrumented program with the guard condition false and observing the
   probe fire anyway.
3. **Exit code is program state on this corpus, not a verdict** (§9) — a
   program that runs correctly can still exit non-zero. Caught by six false
   failures on the first full-corpus run, all on the same field
   (`CA-POLICY-NUM`-adjacent paths in `lgapdb01`), which does not compile-error
   and is only visible by actually executing the instrumented binary.

None of these were guessable from reading the AST or the transformed source in
isolation — each needed an actual `cobc` compile-and-run cycle to surface,
which is why `tests/unit/test_testgen.py` includes real compile-and-run
integration tests (skipped automatically when GnuCOBOL or the AST server is
unavailable) rather than relying on unit tests against synthetic fixtures
alone.

## 11. Known scope limits (v1, not blocking)

- **`EVALUATE`/`WHEN` and non-trivial `PERFORM` are not tracked as blocks.**
  Confirmed unverified against the sample AST when this was scoped; a
  `WHEN` clause currently reads as covered the instant its enclosing
  paragraph is entered. Phase 2 per the original plan.
- **An `IF` without an `ELSE` reports no false-path block.** Branch coverage
  therefore undercounts the untaken side of a bare `IF`. A join-point probe
  right after `END-IF`, inferring "join fired AND then-probe did not," is the
  documented follow-up.
- **`GO TO`-based routing** (this corpus uses it heavily —
  `IF EIBCALEN > 0 GO TO A-GAIN.` is the entry pattern in every `lgtestpN`
  program) means paragraph-entry coverage does not read top-to-bottom like the
  source does. This is exactly why probes are placed by block, not by line
  number.
- **Reachability is capped by the mocks, not by the number of test cases.**
  Across the `lgtestpN` family, a mocked `RECEIVE MAP` overwrites the very
  input field (`ENP1OPTO`-style) that the subsequent `EVALUATE` switches on
  — and where the output record `REDEFINES` the input record, writing the
  output field is undone by the mock's later write to the input field over
  the same bytes. No initial value chosen for a test case can change that
  outcome; the prompt tells the model to recognise the pattern and say so in
  a test case's description rather than invent an initial value for a
  condition it cannot actually influence. Raising the coverage ceiling here
  needs overridable mocks — a change to the transformation pipeline itself,
  out of scope for this addition.
- **Stale goldens are a deliberate, not automatic, re-bless.** If
  `cobol_transformer`'s transformation logic changes and a program's
  semantics shift, previously frozen `expected_values` can go stale.
  Regenerating them is `oracle_runner.py --force`, run on purpose — the same
  tradeoff as any golden-master test suite.
