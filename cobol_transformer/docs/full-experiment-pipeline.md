# Full Experiment Pipeline: From Raw Mainframe COBOL to Judge Verdicts

This is the end-to-end runbook for repeating the whole experiment — mocking,
instrumentation, test generation, mutation authoring, and LLM-judge
verdict generation — on a **new** set of mainframe COBOL programs. Each
stage names every CLI option available, what it's for, and the decision
points a new corpus will force you to make. The six stages are additive and
run in order:

```
raw COBOL (genapp-files/src/)
  -> [1] transform            -> transformed/<program>.cbl        (mocked, runnable locally)
  -> [2] generate_testcases   -> testsuites/<program>/testN.json   (inputs only, no expected values yet)
  -> [3] oracle_runner        -> testsuites/<program>/testN.json   (frozen expected_values)
  -> [4] run_and_report       -> reports/<program>/...             (baseline pass/fail + coverage)
  -> [5] mutgen (manual)      -> modification_quantity/<variant>/mutants/<program>/{P_prime.cbl, intent.md, P_double_prime.cbl}
                              -> modification_quantity/<variant>/mutation_runs/<program>/{pprime,pdprime,results.json}
  -> [6] judge                -> judge_results/results/<variant>/<program>/<label>/<condition>/<backend>-<model>/verdicts.json
```

Stages 1-4 are the existing `cobol_transformer`/`testgen` pipeline and are
almost entirely mechanical (one CLI invocation per program). Stage 5 is
**not** mechanical — it's an author-and-measure loop you drive by hand,
described as a process below. Stage 6 is mechanical again once stage 5's
artifacts exist.

---

## 0. Prerequisites

| Requirement | Needed for | Notes |
|---|---|---|
| Python 3.9+ | everything | no `requirements.txt`/`pyproject.toml` exists — the whole Python side is stdlib-only except stage 5/6's extras below |
| GnuCOBOL (`cobc`) | stages 1, 3, 4, 5 | invoked through WSL on Windows automatically by `gnucobol/gnucobol_runner.py`; must be installed and on `PATH` inside WSL |
| Java 21 + IBM Z Open Editor extension + the AST server | stages 1, 4, 5 (coverage) | optional — everything falls back to a lexical detector/skips coverage if unreachable, but the AST backend gives far higher-fidelity mock detection and is what block-level coverage is built from |
| `claude` CLI on `PATH`, logged in | stage 2 (test generation) and stage 6 (judge, `claude-cli` backend) | authenticates via your account's own session, **not** a separate API key — usage is shared across every headless invocation you make (see Gotchas) |
| `pip install mcp litellm` | stage 6 only | `mcp` is the tool-server SDK; `litellm` is only needed if you use the plug-and-play `litellm` judge backend instead of `claude-cli` |

### Starting the AST server (optional but recommended)

```bat
cobol-ast-server.bat --port 4010
```
(`cobol-ast-server.sh` on Linux/macOS.) Requires `target/cobol-ast-generator.jar`
to exist first (`mvn package` in `java-cli/`). Useful flags: `--lsp-root <path>`
if the Z Open Editor extension isn't auto-detected under
`%USERPROFILE%\.vscode\extensions`, `--max-heap <mb>`, `--timeout <sec>`
(per-request AST wait), `--quiet`. Every stage that can use the AST server
defaults to `http://127.0.0.1:4010` and silently falls back to the lexical
detector (stage 1) or skips coverage (stage 4/5) if it's unreachable — check
your transform's `--report` output for `detection_backend: "lexical"` if a
program that should be AST-parsable isn't.

### Where new source goes

Drop the new programs (and any copybooks they `COPY`) into a source
directory analogous to `genapp-files/src/` — the copybook resolver defaults
to searching the **same directory as the source file**, so no `--copybooks`
flag is needed unless copybooks live elsewhere.

---

## 1. Stage 1 — Transform (mock the mainframe resource statements)

This is what makes "resource statements not runnable locally" (`EXEC CICS`,
`EXEC SQL`, `DFHRESP` macros, VSAM `EXEC CICS READ/WRITE`, BMS map I/O, etc.)
runnable: every such construct is **commented out in place** and replaced
with a deterministic mock inserted directly below it, leaving everything
else byte-for-byte identical.

```
python -m cobol_transformer.cli <subcommand> SOURCE.cbl [options]
```

Subcommands, from cheapest to most complete:

| Subcommand | What it does |
|---|---|
| `inline` | copybook expansion only, no mocking |
| `detect` | lists constructs that *would* be mocked, without writing anything |
| `transform` | full transformation, writes the runnable `.cbl` |
| `build` | `transform` + compile with GnuCOBOL (+ optionally run it) |
| `verify` | reverses a transformed file's mocks and diffs against the original — the byte-identical-outside-mocks guarantee |

Options common to all subcommands:

| Option | Meaning |
|---|---|
| `--copybooks DIR` (repeatable) | extra copybook search directories, beyond the source file's own directory |
| `--continue-on-missing-copybook` | emit a placeholder instead of failing when a `COPY` target can't be found — use this on a first pass over an unfamiliar corpus to see how far it gets, then resolve missing copybooks |
| `--no-ast` | force the lexical fallback detector instead of the AST server (use if the AST server rejects a construct the language server's CICS validator doesn't like — see Gotchas) |
| `--ast-url AST_URL` | AST server location, default `http://127.0.0.1:4010` |
| `--seed SEED` | seed for any randomized mock values (mocks are otherwise deterministic) |
| `--rows-per-cursor N` | how many rows a mocked SQL cursor returns before SQLCODE 100 (end-of-data) — raise this if a new program's cursor-driven logic needs more than one iteration to reach interesting branches |
| `--quiet` | suppress progress output |

`transform`/`build`/`inline` additionally take:

| Option | Meaning |
|---|---|
| `-o, --output PATH` | where to write the transformed `.cbl` (conventionally `transformed/<program>.cbl`) |
| `--manifest PATH` | write the JSON manifest (mock count, backend used, diagnostics) — conventionally `transformed/<program>.manifest.json` |
| `--report PATH` | write a human-readable report — conventionally `transformed/<program>.report.txt` |
| `--save-expanded PATH` | (transform/detect/build only for `--save-expanded`, but `transform`/`inline` share the option) dump the copybook-expanded-but-unmocked intermediate text, useful for debugging a copybook resolution issue |

`build` additionally takes:

| Option | Meaning |
|---|---|
| `--run` | compile *and* execute the result |
| `--run-timeout N` | seconds before the run is killed |
| `--gnucobol-flags "..."` | extra flags passed straight to `cobc` |

### Batch-transforming a new corpus

For more than a couple of programs, don't hand-invoke the CLI per file —
write a small driver mirroring `build_selection.py` (repo root), which
calls the library functions directly (`pipeline.run`, `output.writer.write_outputs`,
`verify.verify`, `gnucobol.gnucobol_runner.GnuCobolRunner`) in a loop, prints
a one-line status table per program (LOC, backend used, mock count,
verify/compile/run status), and flags any program that fell back to the
lexical backend as worth a closer look. This project's own corpus excluded
five programs the Z Open Editor language server's CICS validator refuses to
parse outright (`SEND TEXT ... WAIT` and `ASIS` without `TERMINAL`) — expect
your new corpus to have its own handful of AST-server-hostile programs;
`--no-ast` (lexical fallback) still transforms them, just with lower-fidelity
detection.

### Picking which programs are worth carrying through the whole pipeline

Not every transformed program is a good candidate for stages 5-6. Skip (or
budget extra iteration for) programs where:
- **The whole thing is a `RECEIVE MAP`-driven menu.** If a mocked
  `RECEIVE MAP` unconditionally overwrites the very field a subsequent
  `EVALUATE` switches on, every test converges on the same `WHEN OTHER`
  branch regardless of input — there's no way to get a clean ~50/50 mutant
  split without an unreasonable amount of iteration. (This project hit
  exactly this with its `lgtestp1-4` menu family and swapped in different
  programs instead.)
- **It has zero branch logic** (pure straight-line data movement) — fine for
  stages 1-4, but gives the mutation exercise (stage 5) very little to work
  with.

Programs with a `IF EIBCALEN = 0` guard + a length check + one dispatch
point (`EVALUATE`/compound `IF` on a request-id field) + a handful of
`EXEC SQL`/`EXEC CICS` mocks are the sweet spot — this covers the majority
of a typical CICS/DB2 "one transaction per program" mainframe corpus.

---

## 2. Stage 2 — Generate a Test Suite

```
python -m cobol_transformer.testgen.generate_testcases <transformed_dir> [options]
```

| Option | Meaning |
|---|---|
| `--out DIR` | where test suites are written, default `testsuites` |
| `--claude-bin PATH` | the `claude` executable, default `claude` on `PATH` |
| `--program NAME` (repeatable) | limit to specific programs; omit to process every `.cbl` in `transformed_dir` |
| `--min-tests N` | floor (not target) on cases per program, default 15 — enforced on the output count, not just requested in the prompt |
| `--timeout N` | seconds to wait for the `claude` subprocess |
| `--force` | regenerate even if test cases already exist for a program |
| `--dry-run` | write the prompt to `<out>/<program>/prompt.txt` without calling `claude` — useful for inspecting exactly what the model will see before spending a call |
| `--quiet` | suppress progress output |

This invokes `claude -p` headlessly (prompt piped over **stdin**, never
argv — a large prompt hits Windows' ~32,767-char `CreateProcess` limit
otherwise), scoped via `--add-dir` to just that program's own testsuite
directory. The model only picks `initial_values` and
`variables_to_check` — **never** `expected_values** — because a model can
plausibly guess at what a mocked construct does but cannot reliably hand-trace
it; a wrong guess baked in as an expectation would make a broken suite report
success forever. Every generated case is schema-validated against the real
symbol table (unknown variable name, value that won't fit the field's
PICTURE, or a stray `expected_values` key are all rejected before
acceptance).

### Fallback: hitting the `claude` session/usage limit mid-corpus

Every headless `claude -p` call (this stage, and both judge backends in
stage 6) draws on the **same account session quota**, not a per-call budget.
On a large corpus you will likely hit
`You've hit your session limit · resets <time>` partway through. When that
happens, you don't have to wait it out — write the test case JSON files
**yourself**, following the exact same schema, then run the real oracle
(stage 3) to fill in the expected values. You are still only playing the
"model picks inputs" role the automated step would have played; the ground
truth still comes from a real compile+run, so correctness is unaffected.

**Test case JSON schema** (one file per test, `testsuites/<program>/testN.json`):
```json
{
  "test_id": "test1",
  "program": "<program>",
  "description": "<why this input was chosen, what branch/boundary it hits>",
  "initial_values": {"<VARIABLE>": "<value as a string>"},
  "variables_to_check": ["<VARIABLE>", "..."],
  "generated_by": "claude"
}
```
Omit `expected_values` entirely — stage 3 fills it in. Good coverage of a
typical CICS transaction program's decision points:
- The `EIBCALEN = 0` / no-commarea abend path.
- The commarea-length boundary: one below, exactly at, and one above the
  required length (and, if the length constants themselves are settable
  fields, a case that overrides them to prove the threshold is computed at
  runtime, not hard-coded).
- One case per recognized dispatch value (`EVALUATE`/compound `IF` on a
  request-id field) plus one for the unrecognized/`WHEN OTHER` case and one
  for the blank/SPACES equivalence class.
- Case-sensitivity of any literal string comparison (`'ON'` vs `'on'`).
- Any field whose mock forces a value regardless of input — write these as
  explicit "dead code" documentation cases (set a contradicting initial
  value, assert the mock's value still wins) rather than skipping them; they
  materially help later stages reason about what a mutation can and can't
  observably affect.
- Min/max boundary values for every numeric field's PICTURE width.

---

## 3. Stage 3 — Oracle-Bless the Test Suite

```
python -m cobol_transformer.testgen.oracle_runner <testsuite_dir> [options]
```

| Option | Meaning |
|---|---|
| `--transformed-dir DIR` | default `transformed` |
| `--instrumented-dir DIR` | default `instrumented` — where the oracle-mode `.cbl` files land, `<dir>/<program>/oracle/testN.cbl` |
| `--program NAME` | defaults to the testsuite directory's own name |
| `--force` | re-bless cases that already have `expected_values` (use after hand-editing a test case, e.g. adding a checked variable) |
| `--keep-going` | don't stop at the first case that fails to bless |
| `--run-timeout N` | seconds |
| `--gnucobol-flags "..."` | extra `cobc` flags |
| `--quiet` | suppress per-case progress lines |

This compiles+runs each case against the **real, unmutated** program with
its `initial_values` and reads back a `TC:DUMP:<var>=<value>` line per
checked variable — that observed value becomes `expected_values`, and only
now is the case considered frozen. A case whose oracle run doesn't emit a
value for every checked variable (e.g. the program exits on a path that
skips the dump) is refused, not half-blessed. **A negative exit code is the
only failure signal** — a non-zero-but-positive `RETURN-CODE` is ordinary
program state in this style of program, not a verdict on the run.

---

## 4. Stage 4 — Regression + Coverage Baseline

```
python -m cobol_transformer.testgen.run_and_report <testsuite_dir> [options]
```

| Option | Meaning |
|---|---|
| `--transformed-dir DIR` | default `transformed` |
| `--instrumented-dir DIR` | default `instrumented`, checked-mode files land in `<dir>/<program>/checked/testN.cbl` |
| `--out DIR` | default `reports` |
| `--program NAME` | defaults to the testsuite directory's own name |
| `--ast-url URL` | default `http://127.0.0.1:4010` — **required reachable** for this stage; coverage is computed from a live AST manifest |
| `--run-timeout N` | seconds |
| `--gnucobol-flags "..."` | extra `cobc` flags |
| `--quiet` | suppress per-case progress lines |

This is the repeatable, AI-free regression run: instruments each frozen case
in **checked** mode (init `MOVE`s + `TC:CHK:<var>:MATCH=Y/N:ACTUAL=...` +
`TC:COV:<block-id>` probes), compiles, runs, and writes
`<out>/<program>/testN.report.json` (per-variable expected/actual/match plus
per-test block/line coverage) and `<out>/<program>/suite_summary.json`
(union coverage across the whole suite, pass/fail table,
`blocks_never_hit`). Also (re)writes `<testsuite_dir>/coverage_manifest.json`
— the block inventory (paragraph/section entry + `IF`-THEN/ELSE only in v1;
`EVALUATE`/`WHEN` and non-trivial `PERFORM` are not tracked). Run this once
after stage 3 to confirm a clean 100%-pass baseline before touching anything
in stage 5 — every later mutant's "failing" set is measured relative to this
baseline, so it needs to actually be all-green first.

---

## 5. Stage 5 — Author Mutants (the manual author-measure loop)

This is where you stop running a script and start reading code. For **each**
program you carry forward, you produce, twice over (once per "variant" —
see below): a mutant `P'` with a natural-language `intent.md`, then a
further mutant `P''`, verified against the **same, untouched** frozen test
suite `T` via a small reusable harness.

### The hard constraints (apply to every program, every variant)

- `|F'| / |T| ≥ 0.5` — at least half of `T` must fail against `P'`.
- `(T - F') ⊆ F''` — every test that still passed on `P'` must fail on `P''`.
- Soft goal: `|F'|` and `|F'' - F'|` as close to a 50/50 split of `|T|` as
  the suite size allows.
- Every test in every run must show `compile_ok: true` and `run_ok: true` —
  a "failing" test must be a genuine value mismatch, never a broken build.
- `P'` must actually implement what `intent.md` says, and **nothing else** —
  after writing `P'`, diff it against `P` line-by-line and confirm every
  changed line is accounted for by the intent text (see §5.4).

### 5.1 Two variants: small diff vs. large diff

This project ran the exercise twice per program to study whether the *size*
of a change (not just its content) affects downstream tasks:

- **`mutant1`** — surgical, 1-4 line edits directly on the literal(s) that
  drive the target behavior (e.g. `MOVE 1 TO LastCustNum` → `MOVE 2 TO
  LastCustNum`).
- **`mutant2`** — the *same kind* of semantic change, delivered as a
  ~50-100 line diff per step (`P`→`P'` and separately `P'`→`P''`, measured
  each time via `diff A B | grep -c "^[<>]"`). The reliable recipe:
  1. Add a new `AUDIT-TRANSACTION-EVENT` paragraph + supporting
     `WORKING-STORAGE` fields (sequence number, severity, a simple additive
     checksum) that logs a structured line at every exit point — purely
     additive, must not touch any variable any test checks.
  2. Optionally extract an existing inline validation `IF` into its own
     paragraph as a **pure refactor** — behaviorally identical to the
     original. This is the easiest place to introduce an accidental
     regression (e.g. resetting an accumulator field a test relies on
     *not* being reset) — after writing it, run the harness and confirm
     every test you did *not* intend to touch is still passing for the
     right reason.
  3. Re-implement the actual behavior-changing edit as a multi-step "base +
     offset" computation (`MOVE 1 TO WS-X-BASE`, `MOVE 1 TO WS-X-OFFSET`,
     `ADD WS-X-BASE WS-X-OFFSET GIVING <target>`) instead of a one-line
     literal change — same end effect, much larger diff.
  4. For a literal string mock, use `STRING <parts> DELIMITED BY SIZE INTO
     <target>` composed from a named base field instead of a flat literal.

You can run just one variant on a new corpus, or both if you want the same
size-of-change comparison.

### 5.2 The harness

Reused unmodified regardless of how big the mutation is — it only compiles
and runs whatever `.cbl` you hand it against the frozen suite:

```
python -m cobol_transformer.mutgen.harness run <program> <mutant_path> <label> [options]
python -m cobol_transformer.mutgen.harness compare <program> <prime_label> <double_prime_label> [options]
```

`run` takes positional args `program mutant_path label` (`label`
conventionally `pprime` for `P'`, `pdprime` for `P''`); `compare` takes
`program prime_label double_prime_label` (conventionally `pprime pdprime`).
Options:

| Option | Applies to | Meaning |
|---|---|---|
| `--base-dir DIR` | both | where the isolated per-mutant workspace + `failing_tests.json`/`results.json` land, default `mutation_runs` — **always set this** to `modification_quantity/<variant>/mutation_runs` so `mutant1`/`mutant2` don't collide and so the real `testsuites/`/`transformed/` are never touched (the harness copies the mutant into an isolated `transformed/`-shaped directory and the frozen test JSON into an isolated `testsuites/`-shaped one, specifically because `run_and_report` writes `coverage_manifest.json` back into whatever test directory it's pointed at) |
| `--testsuite-dir DIR` | both | defaults to `testsuites/<program>` — override only if your frozen suite lives elsewhere |
| `--ast-url URL` | `run` only | default `http://127.0.0.1:4010` |

`compare` writes `<base-dir>/<program>/results.json`:
```json
{
  "total_tests": N, "f_prime": [...], "f_prime_count": N, "f_prime_ratio": 0.0,
  "f_prime_meets_50pct": true, "t_minus_f_prime": [...],
  "f_double_prime": [...], "f_double_prime_count": N,
  "t_minus_f_prime_subset_of_f_double_prime": true, "violating_tests": [],
  "f_double_prime_minus_f_prime": [...], "f_double_prime_minus_f_prime_count": N,
  "split_delta": N
}
```
This file is later the **only** source of ground truth stage 6 reads —
nothing downstream re-derives it.

### 5.3 The authoring loop, concretely

1. Read the program's transformed source and its test suite's
   `description` fields — the descriptions already narrate which
   branch/condition each test exercises, which is free signal for
   predicting a mutation's blast radius.
2. Pick a literal or small piece of logic to change; predict by hand which
   tests it should flip.
3. Write `mutants/<program>/P_prime.cbl`, run:
   `harness run <program> mutants/<program>/P_prime.cbl pprime --base-dir modification_quantity/<variant>/mutation_runs`,
   and compare the **actual** failing set against your prediction. Trust
   the compiled result over your prediction every time they disagree — a
   mismatch usually means the mutation cascaded further than expected
   (e.g. corrupting a dispatch discriminator doesn't just break the one
   field check, it re-routes the whole `EVALUATE`).
4. Once `|F'|/|T| ≥ 0.5`, write `intent.md` (50-60 words, plain prose,
   describing exactly and only what you changed).
5. Copy `P_prime.cbl` → `P_double_prime.cbl`, add edits targeting the
   specific `T - F'` set from the last `run`, re-run the harness for
   `pdprime`, then `compare`. Iterate the *choice* of literal (not the
   intent) until both hard constraints hold.
6. You are explicitly allowed to edit an existing test case (e.g. add a
   variable to `variables_to_check`, then re-bless with
   `oracle_runner ... --force`) to nudge the split — this changes which
   tests are in `F'`/`F''-F'`, not the mutation itself, and is a legitimate
   tool for hitting the 50/50 target when the code itself doesn't cooperate.

### 5.4 Auditing `intent.md` against the actual diff

Before trusting a mutant, `diff transformed/<program>.cbl
mutants/<program>/P_prime.cbl` and check every hunk is accounted for by the
intent text — nothing more, nothing less. Two failure modes to watch for
specifically (both found and fixed during this project's own audit):
- A **misleading comment**: code declares "derived from a base plus an
  offset" scaffolding fields that are actually never wired into the real
  computation (a leftover from an earlier draft) — the fields sit unused.
  Catch this mechanically: every newly-declared `01 WS-*` field should
  appear at least twice in the file (once declared, at least once used);
  anything appearing only once is dead.
- An **undocumented supporting change**: e.g. an added
  `MOVE 0 TO CA-RETURN-CODE` that makes a new audit-logging feature's
  severity check well-defined, but isn't mentioned in the intent. Confirm
  via the actual test reports whether it changes any test's outcome — if
  not, it's a legitimate omission to fix by *editing the intent text*, not
  the code (editing the code means re-verifying the whole mutant).

---

## 6. Stage 6 — Run the Judge (verdict generation)

Classifies each failing test on a mutant as `OBSOLETE` (the intent
legitimately changed that behavior — the test just hasn't been updated) or
`BUG_TRIGGERED` (the modification did something the intent doesn't
authorize).

### 6.1 Ground truth (derived, never hand-labeled)

From `modification_quantity/<variant>/mutation_runs/<program>/results.json`:
- Judging `P'` (`label=pprime`): every test in `F'` is `OBSOLETE` — `P'` is
  built and verified to have no accidental bugs by construction.
- Judging `P''` (`label=pdprime`): a test is `OBSOLETE` if it's in `F'`,
  `BUG_TRIGGERED` if it's only in `F'' - F'`. The **same** `intent.md`
  (describing only the authorized `P → P'` step) is used for both.

```
python -m cobol_transformer.judge.ground_truth <variant> <program> <label>
```

### 6.2 Prepare a case (sandbox the agent is allowed to see)

```
python -m cobol_transformer.judge.prepare_case <variant> <program> <label> [--cases-root DIR] [--force]
```
Builds `judge_results/cases/<variant>/<program>/<label>/`:
`sandbox/{original.cbl, modified.cbl, intent.md}` (readable by the agent)
plus `_data/{testcases.json, coverage.json}` (only reachable through the MCP
tools below, never as raw files) — pulled straight from stage 4/5's report
JSON, no new computation. `run_judge` (below) calls this automatically; run
it standalone only to inspect a sandbox before spending an agent call on it.

### 6.3 The four MCP tools (`tools_server.py`)

One server process per case (`python -m cobol_transformer.judge.tools_server
<case_dir> <output_dir>`), so no tool takes a directory/session argument:

| Tool | Signature | Returns |
|---|---|---|
| `read_file` | `path` — one of `"original.cbl"`, `"modified.cbl"`, `"intent.md"` | raw text |
| `get_failing_testcases` | *(no args)* | every in-scope test: `description`, `initial_values`, `mismatches: [{variable, old_expected, actual_new}]` |
| `get_coverage` | `test_id` | `{original_run, modified_run}` block coverage, each `{blocks_hit: [{id, kind, name, line_start, line_end}], block_coverage_pct}` |
| `write_file` | `path` (filename only), `content` | writes the final `verdicts.json` to this case's output directory |

Extend this file with your own tools as needed (e.g. a `diff(file_a,
file_b)` tool) — it's deliberately small.

### 6.4 The classification prompt

`prompts/obs_vs_bug_v2.md` is the reference prompt — read it for the exact
reasoning procedure (compute `CORRECT_NEW` independently from the intent,
compare against `OLD_EXPECTED`, decision table, output schema). Reuse it
verbatim on a new corpus; it makes no assumption about program names or
field names. If you write your own variant, keep the contract: the agent
must call `write_file("verdicts.json", ...)` with
`{"verdicts": [{"test_id", "verdict": "OBSOLETE"|"BUG_TRIGGERED", "justification"}]}`.

### 6.5 Running it

```
python -m cobol_transformer.judge.run_judge \
  --variant mutant1 --program <program> --label pprime \
  --condition treatment --backend claude-cli \
  --model claude-haiku-4-5 --effort low \
  --prompt-file prompts/obs_vs_bug_v2.md
```

| Option | Meaning |
|---|---|
| `--variant {mutant1,mutant2}` | which mutation set to judge |
| `--program NAME` | |
| `--label {pprime,pdprime}` | which mutant, `P'` or `P''` |
| `--condition {baseline,treatment}` | `baseline` = no MCP tools, no prompt file — everything inlined into one text blob with a one-line generic system prompt (the deliberately-worst-case control); `treatment` = your prompt file + the four tools |
| `--backend {claude-cli,litellm}` | see below |
| `--model NAME` | `claude-cli`: any `claude` CLI model alias/name; `litellm`: any `<provider>/<model-name>` string |
| `--effort LEVEL` | `claude-cli`: passed straight to `--effort` (`low`/`medium`/`high`/`xhigh`/`max`); `litellm`: passed as `reasoning_effort` if the provider supports it |
| `--prompt-file PATH` | required for `treatment`; ignored for `baseline` |

Output lands in `judge_results/results/<variant>/<program>/<label>/<condition>/<backend>-<model>/{verdicts.json, transcript.jsonl}`.

**Backend choice**: `claude-cli` wraps a headless `claude -p` the same way
stage 2 does, and shares that account's session quota. `litellm` is the
plug-and-play path — swapping the underlying model/provider for a new
corpus (or to compare judges) is purely the `--model` string
(`anthropic/claude-haiku-4-5`, `openai/gpt-4o-mini`,
`groq/llama-3.1-70b-versatile`, ...), with the matching provider API key
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, ...) set in the
environment — no code change either way.

### 6.6 Scoring

```
python -m cobol_transformer.judge.score --variant mutant1 --program <program> --label pprime --condition treatment --backend claude-cli --model claude-haiku-4-5
python -m cobol_transformer.judge.score --all   # every run found under results/, aggregated
```
Reports accuracy, per-class confusion counts, `false_bug_rate` (fraction of
true `OBSOLETE` wrongly called `BUG_TRIGGERED` — the calibration metric a
better prompt/tools should move), `bug_recall`, `bug_precision`. To get a
single "accuracy separately for obsolete vs. buggy" number across many
cases, pool every case's `score_one(...)["rows"]` and compute per-class
accuracy over the pooled rows (see the interactive snippet used to produce
this project's own headline numbers — same idea, no new script needed for a
new corpus, just loop the same call over your new program list).

---

## 7. Gotchas (all found the hard way, once each — check this list first)

| Symptom | Cause | Fix |
|---|---|---|
| `WinError 206` / command line too long | a large prompt passed as an argv element | pipe it over **stdin** (`subprocess.run(..., input=prompt)`), never argv — already how stages 2 and 6 work |
| A branch probe silently makes a guarded statement run unconditionally | an inserted `DISPLAY` inside an `IF`'s body ends with a period, closing the sentence early | branch-body probes must never carry their own trailing period (paragraph-entry probes are fine with one) |
| A continued literal reads as truncated/space-padded oddly | fixed-format COBOL: a literal continued past column 72 needs the continuation line padded to *exactly* column 72, not just to its own content length | pad continuation lines to column 72 |
| A test with a nonzero exit code looks like it "failed" but everything else matches | `RETURN-CODE` is ordinary program state in these mocked transactions, not a pass/fail verdict — one real program in this corpus exits 32 on a perfectly successful run | only a **negative** return code (subprocess timeout) is a real failure signal |
| A numeric field that displays blank gets asserted as `0` | an uninitialized numeric field on some path was never written | refuse the comparison (raise), don't silently assert a guessed value |
| A numeric-edited field's length guard rejects a legal value | `length` on a `PIC +9(5)`-style field counts print columns (6, including the sign), not digits (5) | skip the length guard for `NUMERIC_EDITED`, or count columns not digits |
| `UnicodeEncodeError` piping a prompt containing `≠`/`·`/etc. to `claude -p` on Windows | `subprocess.run(..., text=True)` defaults to the console's `cp1252` encoding, not UTF-8 | pass `encoding="utf-8", errors="replace"` explicitly |
| An MCP-tooled agent reports zero tools available, `python -m package.module` `ModuleNotFoundError` | the spawned MCP server subprocess's cwd isn't the repo root, and the package isn't pip-installed, so `-m` resolution fails silently from the tool-caller's point of view | set `PYTHONPATH` to the repo root explicitly in the MCP server's `env`, don't rely on inherited cwd |
| `claude -p --mcp-config ... --safe-mode` never sees the configured tools | `--safe-mode`'s own help text says it disables "MCP servers" among other customizations — it's not compatible with wanting a custom MCP server active | drop `--safe-mode`; `--restricted` alone (with an explicit `--disallowedTools` list) is enough sandboxing |
| `claude -p --restricted --strict-mcp-config --mcp-config ...` never sees the configured tools either | per `--restricted`'s own help text, adding `--strict-mcp-config` under `--restricted` **disables MCP servers entirely** (the opposite of `--strict-mcp-config`'s standalone meaning of "only use this config") | omit `--strict-mcp-config` when also passing `--restricted`, unless you specifically need to suppress an ambient project/user `.mcp.json` |
| A confused/mis-configured headless agent reaches out over cross-session messaging to another Claude session instead of failing | `SendMessage`/`ListAgents`/`Task*` and friends weren't in the `--disallowedTools` deny list | explicitly deny the whole orchestration/messaging tool family alongside the usual Bash/Read/Write/WebFetch set |
| A batch of `claude -p` calls dies partway with `You've hit your session limit · resets <time>` | every headless invocation (stage 2 and both stage 6 backends) shares one account-level session quota, not a per-call budget | either wait for the reset time, or (for stage 2) hand-author the affected test case JSON yourself and bless it for real in stage 3 — resume a stage-6 batch by only re-running the `(variant, program, label)` combinations still missing a `verdicts.json` |
| One case in a large batch fails with `API Error: 529 Overloaded` | transient Anthropic server-side capacity issue, unrelated to your code | just retry that one case |
| A `claude -p` process exits non-zero but its `write_file` call clearly already succeeded (verdicts.json exists and looks complete) | the session-limit/overload error can land *after* the agent's tool calls already completed, while it was generating its closing summary text | trust the presence of a well-formed `verdicts.json` over the process's exit code when auditing a batch run's failures |
| A test with multiple mismatching fields gets judged `BUG_TRIGGERED` when ground truth says `OBSOLETE` (or vice versa) | the ground truth is **per-testcase** (via `F'`/`F''` set membership), but a correct field-level read of the code can find that some of a test's mismatches are intent-authorized *and others aren't*, on the very same test | not a bug — an inherent ceiling on accuracy for compound-cause tests; consider it separately from single-cause tests when interpreting results, and prefer the `P'`-only accuracy (zero compound-cause ambiguity by construction) as the cleaner calibration signal |

---

## 8. Quick-reference command sequence for one new program

```bash
# 1. Transform
python -m cobol_transformer.cli build genapp-files/src/<program>.cbl \
    -o transformed/<program>.cbl --manifest transformed/<program>.manifest.json \
    --report transformed/<program>.report.txt --run
python -m cobol_transformer.cli verify genapp-files/src/<program>.cbl

# 2. Generate a test suite (or hand-author if the session quota is exhausted)
python -m cobol_transformer.testgen.generate_testcases transformed --program <program>

# 3. Freeze expected values against the real program
python -m cobol_transformer.testgen.oracle_runner testsuites/<program> --keep-going

# 4. Baseline regression + coverage (confirm 100% pass before stage 5)
python -m cobol_transformer.testgen.run_and_report testsuites/<program>

# 5. Author P', intent.md, P'' by hand (see Stage 5), verifying with:
python -m cobol_transformer.mutgen.harness run <program> mutants/<program>/P_prime.cbl pprime \
    --base-dir modification_quantity/mutant1/mutation_runs
python -m cobol_transformer.mutgen.harness run <program> mutants/<program>/P_double_prime.cbl pdprime \
    --base-dir modification_quantity/mutant1/mutation_runs
python -m cobol_transformer.mutgen.harness compare <program> pprime pdprime \
    --base-dir modification_quantity/mutant1/mutation_runs

# 6. Judge
python -m cobol_transformer.judge.run_judge --variant mutant1 --program <program> --label pprime \
    --condition treatment --backend claude-cli --model claude-haiku-4-5 --effort low \
    --prompt-file prompts/obs_vs_bug_v2.md
python -m cobol_transformer.judge.run_judge --variant mutant1 --program <program> --label pdprime \
    --condition treatment --backend claude-cli --model claude-haiku-4-5 --effort low \
    --prompt-file prompts/obs_vs_bug_v2.md
python -m cobol_transformer.judge.score --variant mutant1 --program <program> --label pdprime \
    --condition treatment --backend claude-cli --model claude-haiku-4-5
```

Repeat stage 5-6 with `mutants/<program>/P_double_prime.cbl` restructured to
the `mutant2` large-diff style, and `--variant mutant2` throughout, if you
want the size-of-change comparison too.
