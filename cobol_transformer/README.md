# cobol_transformer

Turns IBM GenApp mainframe COBOL (CICS + DB2 + VSAM) into self-contained
programs that compile and run under GnuCOBOL, by **commenting out** each
statement that needs a mainframe at run time and inserting a deterministic mock
directly below it.

Nothing else in the program is touched. That is not an aspiration — it is
checked mechanically by `cobol_transformer verify`, which reverses the
transformation and diffs the reconstruction against the input byte for byte.

> **Detailed implementation documentation is in [`../docs/`](../docs/README.md)**
> — nine documents covering each component, plus an end-to-end walkthrough of a
> real program through all eight stages.
>
> **The test-generation pipeline built on top of `transformed/*.cbl` is
> documented separately in [`docs/testgen.md`](docs/testgen.md).**

## Results on the GenApp corpus

The current deliverable is scoped to the **26 programs the AST backend can
parse**. Five (`lgicvs01`, `lgipvs01`, `lgsetup`, `lgstsq`, `lgtestc1`) are
excluded because the language server refuses to emit an AST for them; the
lexical fallback still handles them, and the full-corpus figures are given for
reference.

| | AST scope (26) | Full corpus (31) |
|---|---|---|
| Programs transformed | **26 / 26** | **31 / 31** |
| Compile with `cobc -x` | **26 / 26** | **31 / 31** |
| Run to completion | **26 / 26** | **31 / 31** |
| Verified byte-identical outside mocks | **26 / 26** | **31 / 31** |
| Constructs mocked | 406 | 556 EXEC + 13 `DFHRESP` |
| Generic-fallback rule used | **0** | **0** |
| Constructs skipped | **0** | **0** |

## Usage

```bash
# expand copybooks only
python -m cobol_transformer.cli inline  genapp-files/src/lgstsq.cbl -o out.cbl

# list what would be mocked, write nothing
python -m cobol_transformer.cli detect  genapp-files/src/lgstsq.cbl

# full transformation + manifest + report
python -m cobol_transformer.cli transform genapp-files/src/lgstsq.cbl -o out.cbl

# transform, then compile and run under GnuCOBOL
python -m cobol_transformer.cli build   genapp-files/src/lgstsq.cbl -o out.cbl --run

# prove only the mocked constructs changed
python -m cobol_transformer.cli verify  genapp-files/src/lgstsq.cbl
```

Useful flags: `--copybooks DIR` (repeatable), `--no-ast` (force the lexical
detector), `--rows-per-cursor N` (how many rows a mocked cursor or browse
returns before reporting end-of-data), `--seed N`.

## How it works

```
inline copybooks → AST (or lexical fallback) → classify → anchor → terminator
  → mock rules → comment + insert → inject declarations → write → compile
```

### 1. Copybook inlining happens first, at the text level

The AST cannot see copybook boundaries: `COPY` produces no node at all, and
`EXEC SQL INCLUDE` produces nothing whatsoever. Expansion is therefore a text
pass that runs *before* the AST tool, which then receives one physically
complete file.

Two names have no copybook on disk and are supplied by built-in providers:
`SQLCA` (the standard DB2 layout, which DB2 injects at precompile time) and
`SSMAP` (generated from `ssmap.bms` using the documented symbolic-map
expansion — 6 maps, 84 fields).

### 2. Constructs are found by AST, with a verified fallback

`EXEC CICS`/`EXEC SQL` blocks arrive as `ExecEndExec` nodes and `DFHRESP(...)`
as `CicsDFHRESPmacro`. But the Z Open Editor language server **refuses to emit
an AST at all** when its CICS validator dislikes a command — five GenApp
programs use `SEND TEXT ... WAIT` or `ASIS` without `TERMINAL` and are rejected
outright.

Those still transform, via a lexical detector. That is defensible because the
AST is *blind inside an EXEC block anyway* (the body arrives as unparsed raw
text), so it contributes only the span boundaries — and on all 26 programs
where both paths run, the two produce **byte-identical spans**. That parity is
asserted in `tests/unit/test_detector_parity.py`, not merely assumed.

### 3. Anchoring, never line numbers

AST line numbers drift from physical lines and carry no copybook provenance, so
they are never read. Each node is located by searching for its verbatim
`Source Text` forward from a monotonically advancing cursor, so two identical
statements match their own occurrences instead of collapsing onto the first.
(`Source Text` comes back with CRLF even for LF input, so it is normalised
first.) A node that cannot be located is skipped and reported — never guessed.

### 4. Terminator fidelity

A COBOL period ends a *sentence*; inside an `IF` body it closes the scope.
Emitting one where the original had none — or dropping one — silently changes
control flow. Each statement's terminator is detected structurally and
reproduced exactly: a period only when the original carried one, and only on
the last generated statement.

### 5. Flow-preserving mocks

A mock must return control exactly where the real command did:

- `EXEC CICS RETURN` ends the program → mocked as `GOBACK`. A trace line alone
  would let execution fall into code that never previously ran.
- `EXEC CICS ABEND` terminates → also ends the program.
- `XCTL` transfers away and never returns → `GOBACK`.
- Everything else returns to the next statement → trace plus data population.

`RESP`/`RESP2` and `SQLCODE` are set with numeric literals (0 = success), never
`DFHRESP(NORMAL)`, which is itself untranslatable.

**Loop termination.** A cursor `FETCH` or a browse read (`READQ TS ... NEXT`,
`READNEXT`) sits in a loop that ends only when the resource runs out. The
generated code is static, so the bound cannot be decided while transforming —
the same statement runs on every iteration. Each such site therefore gets a
counter in `WORKING-STORAGE` that does the counting at **run** time and reports
end-of-data once its budget is spent.

### 6. Making programs actually runnable

- **LINKAGE promotion.** `DFHCOMMAREA` is declared in `LINKAGE SECTION` and
  addressed by the caller's commarea under CICS. Standalone there is no caller,
  so those items have no storage. Commenting out the `LINKAGE SECTION.` header
  alone turns the entries that follow into `WORKING-STORAGE` items — same
  declarations, same order, same `REDEFINES`, now with real storage. Sound here
  because every program places LINKAGE right after WORKING-STORAGE and none has
  a `PROCEDURE DIVISION USING` clause (verified across all 31).
- **EIB synthesis.** CICS supplies the EXEC Interface Block at run time and the
  source declares none of it, so referenced fields (`EIBCALEN`, `EIBTRNID`, …)
  are emitted with the PICTURE CICS gives them.
- **Punctuation repair.** `lgwebst5.cbl` is missing the period after its
  `PROGRAM-ID` paragraph. IBM's compiler tolerates it; GnuCOBOL does not. The
  period is added and reported as `W-SYNTAX-REPAIR`.

### 7. Fail-closed, always

| Situation | Behaviour |
|---|---|
| Node's source text not found | skip + `E-ANCHOR-NOT-FOUND`, cursor not advanced |
| Node found only before the cursor | skip + `E-ANCHOR-OUT-OF-ORDER` |
| Live code shares the statement's line | skip + `E-COMMENT-LINE-NOT-PURE`, source untouched |
| Option text won't tokenise | generic fallback rule + `W-FALLBACK-RULE-USED` |
| Unmapped CICS condition | non-zero sentinel + `W-DFHRESP-UNKNOWN` |

An unmocked construct is a visible compile error; a mis-anchored splice would
silently corrupt working code. The first is always preferred.

## Test-case generation, instrumentation & coverage (`testgen/`)

A second, additive pipeline sits on top of `transformed/*.cbl`. Since a
transformed program takes no CLI args or stdin and every mocked CICS/SQL call
is deterministic, its entire behaviour is a pure function of its
`WORKING-STORAGE` initial values — which makes it possible to generate test
cases, run them for real coverage numbers, and re-run them as a regression
suite with no further AI or oracle involvement.

> **Full write-up, including why `expected_values` are never guessed and the
> two GnuCOBOL gotchas that shaped the instrumenter, is in
> [`docs/testgen.md`](docs/testgen.md).**

```bash
# 1. generate >= 15 test cases per program (headless `claude`, one per program)
python -m cobol_transformer.testgen.generate_testcases transformed

# 2. execute each case for real to freeze its expected_values (no AI)
python -m cobol_transformer.testgen.oracle_runner testsuites/lgtestp1

# 3. instrument + compile + run + score coverage (repeatable; no AI, no oracle)
python -m cobol_transformer.testgen.run_and_report testsuites/lgtestp1
```

Run against the full `transformed/` corpus (10 programs, 196 generated cases):
**196/196 passed**, block coverage 19–65% depending on the program (the
`lgtestpN` terminal programs sit lowest because their mocked `RECEIVE MAP`
overwrites the very field their `EVALUATE` switches on, making most `WHEN`
branches unreachable from initial values — a property of the mocks, not of
the test generator).

| | |
|---|---|
| Test cases generated | 196 across 10 programs (≥ 15 each, enforced) |
| Oracle-frozen (ground truth from a real run) | 196 / 196 |
| Passed on re-run | 196 / 196 |
| Block coverage (paragraph/section + IF/ELSE) | 19% – 65.2% per program |

## Layout

```
cobol_transformer/
  cli.py  pipeline.py  verify.py  linetools.py  errors.py
  discovery/copybook_resolver.py     search path + SQLCA/SSMAP providers
  inline/    lexer scanner replacing inliner source_map bms
  ast_client/ ast_model http_client
  analysis/  node_classifier anchor text_detector exec_text_parser
             symbol_table pic_parser
  mocks/     rule_engine rules_cics rules_sql rules_eib rules_fallback
             dummy_values var_allocator codegen cics_conditions.json
  rewrite/   terminator commenter rewriter ws_injector syntax_repair
  output/    manifest writer
  gnucobol/  gnucobol_runner
  testgen/   variable_context cfg literal_format instrumenter
             prompt_builder generate_testcases oracle_runner run_and_report
```

## Tests

```bash
python -m pytest tests/unit -q      # 256 passed, 5 skipped
```

The 5 skips are the parity test on the programs the language server declines to
parse. Tests needing the AST server or GnuCOBOL skip themselves when either is
not running; the end-to-end tests use the lexical detector and need only the
corpus. `tests/unit/test_testgen.py` covers `testgen/` — literal formatting,
fixed-format layout, control-flow extraction, instrumentation, and, where
GnuCOBOL and the AST server are both reachable, real compile-and-run round
trips including a proof that a branch probe cannot leak into its sibling
branch.

## Requirements

Python 3.9+, GnuCOBOL (`cobc`, invoked through WSL on Windows). The AST backend
additionally needs Java 21, the IBM Z Open Editor extension, and the server
started with `cobol-ast-server.bat --port 4010`; without it the tool falls back
to the lexical detector automatically.
