# 5. Mock Generation (Stage 4)

Modules: `mocks/rule_engine.py`, `rules_cics.py`, `rules_sql.py`, `rules_eib.py`,
`rules_fallback.py`, `dummy_values.py`, `var_allocator.py`, `codegen.py`

## 5.1 The rule engine

```python
class MockRule:
    def matches(self, ctx: RuleContext) -> bool: ...
    def generate(self, ctx: RuleContext) -> MockResult: ...
```

Dispatch is first-match-wins over an ordered list, with a guaranteed-matching
fallback last:

```
DfhrespRule  →  CICS_RULES  →  SQL_RULES  →  GenericFallbackRule
```

`GenericFallbackRule.matches()` returns `True` unconditionally, so **every**
construct receives some mock. Reaching it emits `W-FALLBACK-RULE-USED`, so
coverage gaps surface as warnings instead of passing silently. On the corpus it
is currently reached **zero** times.

### `RuleContext`

```python
range, command, category, symbols, indent, had_trailing_period,
declarative, paragraph, sequence, program, values, cursor_state,
config, allocator
```

Three fields deserve comment:

- **`declarative`** — `True` when the construct sits before `PROCEDURE DIVISION`.
  A procedural statement emitted there would not compile. See §5.6.
- **`indent`** — the Area B column of the statement being replaced, so the mock
  lines up with the code around it.
- **`allocator`** — hands out collision-free `WORKING-STORAGE` names for runtime
  counters (§5.5).

### `MockResult`

```python
statements: list[str]          # procedural COBOL, OR
inline_text: str | None        # in-place substitution (DFHRESP only)
working_storage: list[str]
diagnostics: list[Diagnostic]
confidence: "high" | "fallback"
```

## 5.2 `codegen.py` — emitting fixed-format COBOL

Two responsibilities the rest of the layer depends on.

**Column discipline.** Generated text starts at the replaced statement's Area B
column and never runs past column 72. Over-long statements wrap onto further
lines at a deeper indent rather than being truncated:

```python
width = MAX_COL - indent                      # MAX_COL = 72
cont_indent = indent + CONT_EXTRA_INDENT      # +4
```

Wrapping is on spaces, which is safe because COBOL is free-form within Area B.

**Terminator fidelity.** The period goes on the **last** generated statement and
only when the original carried one:

```python
for i, stmt in enumerate(stmts):
    text = stmt.rstrip(".")
    if i == len(stmts) - 1 and terminate_with_period:
        text += "."
```

If a rule produces nothing at all but the original ended a sentence, `CONTINUE`
is emitted to carry the period — the COBOL no-op that can hold a terminator.

## 5.3 `dummy_values.py` — deterministic placeholders

Values come from a static table plus name heuristics. **No clock, no
randomness** — that determinism is what makes golden-file tests and reproducible
builds possible.

| PIC category | Value |
|---|---|
| `NUMERIC` | `0`, or `1` when the name suggests generated output (`NUM`, `-ID`, `COUNT`, `CNT`, `SEQ`) |
| `NUMERIC_EDITED` | `0` |
| `ALPHANUMERIC` / `ALPHABETIC` | see below |
| `POINTER` | **`None`** — skipped |
| `UNKNOWN` | `None` — skipped |

Alphanumeric content is chosen by name shape:

| Name contains | Length | Value |
|---|---|---|
| `DATE`, `DOB` | ≥10 / else | `'2024-01-01'` / `'20240101'` |
| `TIME` | ≥8 / else | `'12:00:00'` / `'120000'` |
| `FLAG`, `-IND`, `-SW` | 1 | `'Y'` |
| anything | 1 | `' '` |
| anything | ≥2 | `'DUMMY'` |

### Truncate, never pad

```python
return base[:length]     # NOT base.ljust(length)
```

`MOVE` already pads an alphanumeric receiving field on the right, so padding
here adds nothing — but it *would* push long literals past column 72, requiring
continuation lines to stay legal. An early version padded, and produced this:

```cobol
              MOVE 'DUMMY                                               
                  ' TO WS-RECV-DATA          <- broken literal, would not compile
```

**Pointers are never given a value.** A fabricated address is meaningless and
risks a runtime fault when dereferenced, so the field is left as it was.

## 5.4 Flow preservation

This is the governing constraint on `rules_cics.py`. A CICS command either
returns control to the next statement or it does not, and the mock must do the
same.

| Verb | Real behaviour | Mock | Why |
|---|---|---|---|
| `RETURN` | control returns to CICS — program ends | trace + **`GOBACK`** | a trace alone would let execution fall into code that never ran |
| `ABEND` | abnormal termination | trace + **`GOBACK`** | same |
| `XCTL` | transfers away, never comes back | trace + **`GOBACK`** | same |
| `LINK` | invokes a program, **returns** | trace only | LINK does return, so continuing is correct |
| everything else | returns to the next statement | trace + data population | flow already continues |

`LINK` deliberately does not `CALL` the target: each program is compiled
standalone, so the module would not be found at run time. Since LINK returns to
its caller, tracing preserves the flow faithfully.

### Status codes

`RESP`/`RESP2` are set with a **numeric literal**, never `DFHRESP(NORMAL)` —
which is itself untranslatable:

```python
def set_resp(ctx, out, value=0):
    for opt in ("RESP", "RESP2"):
        ident = split_arg_identifier(ctx.command.option(opt) or "")
        if ident and ident in ctx.symbols:
            out.append(f"MOVE {value} TO {ident}")
```

The `ident in ctx.symbols` guard matters: without it, `RESP(WS-RESP)` naming a
field that does not exist would generate a `MOVE` to an undeclared name.

### Record population

`populate()` fills a `READ ... INTO(...)` target so downstream logic has
well-defined data:

- an **elementary** field gets one `MOVE`
- a **group** is filled leaf by leaf, each per its own PICTURE, with `REDEFINES`
  siblings skipped (see [symbol table](04-analysis.md#41-symbol_tablepy--the-data-division))
- a group with no usable leaves gets `MOVE SPACES`, so the caller sees a defined
  buffer rather than whatever was there before

## 5.5 Loop termination — the hardest correctness problem

A cursor `FETCH` or a browse read sits inside a loop that ends only when the
resource runs out:

```cobol
           Perform With Test after Until WS-RESP > 0
              Exec CICS ReadQ TS Queue(STSQ-NAME) Into(READ-MSG)
                  Resp(WS-RESP) Next
              End-Exec
              ...
           End-Perform
```

A mock that always reports success makes this **loop forever**.

### The first attempt was wrong

The obvious fix — count occurrences while transforming and emit "success" for
the first *n* — does not work, and it is worth understanding why:

> **The generated code is static.** One `FETCH` statement is *executed*
> repeatedly by its loop. A transform-time counter increments once per
> *statement*, not once per *iteration*, so the single emitted mock says
> "success" on every pass forever.

This actually shipped briefly and hung `lgicvs01` at run time.

### The fix: count at run time

Each such site gets its own counter in `WORKING-STORAGE`, and the emitted code
does the counting:

```cobol
           DISPLAY '>>> MOCK FETCH @FETCH-DB2-POLICY-ROW: ' 'POLICY_CURSOR'
           ADD 1 TO MOCK-FETCH-CNT-4
           IF MOCK-FETCH-CNT-4 > 1 MOVE 100 TO SQLCODE ELSE MOVE 0 TO
               SQLCODE MOVE '2024-01-01' TO DB2-ISSUEDATE MOVE
               '2024-01-01' TO DB2-EXPIRYDATE MOVE 'DUMMY' TO
               DB2-LASTCHANGED MOVE 1 TO DB2-BROKERID-INT ... END-IF
```

The first pass returns a row with `SQLCODE = 0`; every later pass returns
`SQLCODE = 100`, which is exactly what terminates
`PERFORM UNTIL SQLCODE = 100`. Budget is configurable via `--rows-per-cursor`.

The `IF ... END-IF` is emitted as **one statement string** so `codegen` treats it
as a single sentence and the terminator logic stays correct.

Counters are **per site**, not per cursor name, because two `FETCH`es on the same
cursor sit in different loops and each needs its own count:

```python
return self.allocator.allocate(f"{base}-{self.sequence}")
```

The same mechanism covers CICS sequential reads via `bounded_read()`:

| Construct | Exhausted status |
|---|---|
| SQL `FETCH` | `SQLCODE = 100` |
| `READQ TS ... NEXT` | `RESP = 26` (ITEMERR) |
| `READNEXT` / `READPREV` | `RESP = 20` (ENDFILE) |

A `READQ` is treated as sequential when it has the `NEXT` flag or no `ITEM`
option — an item-less read walks the queue.

### `var_allocator.py`

Names are checked case-insensitively against the full symbol table *and* names
already handed out, then suffixed on collision:

```python
while candidate in self.symbols or candidate in self._taken:
    n += 1
    candidate = base[: 26 - len(f"-{n}")] + f"-{n}"
```

## 5.6 Declarative constructs

Three `EXEC SQL DECLARE ... CURSOR` blocks in the corpus live in the **DATA
DIVISION** (they arrive via `LGPOLICY` and inline declarations). They are
declarations, not statements.

`SqlDeclarativeRule` returns no statements when `ctx.declarative`, so the
construct is commented out and nothing replaces it.

This interacts with terminator handling in a way that caused a real bug. The
pipeline normally emits `CONTINUE` when a rule produces nothing but the original
ended a sentence — which put a procedural `CONTINUE.` in the DATA DIVISION and
broke compilation with `PROCEDURE DIVISION header missing`. The guard:

```python
elif rng.had_trailing_period and not ctx.declarative:
    generated[rng.start] = render_statements(["CONTINUE"], ctx.indent, True)
```

A declarative construct's period belonged to a data-division entry, and the
whole entry is inside the comment, so nothing is needed.

## 5.7 The CICS rules

| Rule | Verbs | Behaviour |
|---|---|---|
| `ReturnRule` | RETURN | trace + `GOBACK` |
| `AbendRule` | ABEND | trace with ABCODE + `GOBACK` |
| `LinkRule` | LINK, XCTL, START | trace target; `GOBACK` for XCTL |
| `FileRule` | READ, WRITE, REWRITE, DELETE, browse verbs | READ populates `INTO`; browse verbs bounded; others trace the key |
| `CounterRule` | GET/DEFINE/DELETE/QUERY/UPDATE COUNTER | trace + deterministic integer into `VALUE`/`INCREMENT` |
| `QueueRule` | WRITEQ/READQ/DELETEQ TS/TD | READQ populates `INTO` (bounded when sequential); WRITEQ echoes `FROM` |
| `TerminalRule` | SEND/RECEIVE (+ MAP/TEXT/…) | RECEIVE populates `INTO`/`SET`; SEND echoes `FROM` |
| `TimeRule` | ASKTIME, FORMATTIME | fixed date/time literals, matched to each option and PIC |
| `AssignRule` | ASSIGN | fills every named field per its PICTURE |
| `ContainerRule` | GET/PUT/DELETE CONTAINER | GET populates `INTO` |
| `GetmainRule` | GETMAIN | trace; addressability untouched |
| `NoOpRule` | SYNCPOINT, ENQ/DEQ, HANDLE CONDITION/AID, … | trace only |

**Why `HANDLE CONDITION` as a no-op is correct:** it registers a branch target
for conditions the mocks never raise. Since every mocked resource reports
success, registering nothing preserves the success path exactly.

### Trace format

```
>>> MOCK <verb> @<paragraph>[: detail]
```

Consistent and greppable, which lets `build --run` correlate captured stdout
against the manifest. The paragraph name comes from a map built over
`PROCEDURE DIVISION` — anchored to Area A, and skipping anything inside an EXEC
block, so a line like `           END-EXEC.` is not mistaken for a paragraph
header (it briefly was, producing `@END-EXEC` in traces).

## 5.8 The SQL rules

| Rule | Verbs | Behaviour |
|---|---|---|
| `SqlDeclarativeRule` | DECLARE CURSOR/TABLE, BEGIN, END, WHENEVER | nothing when declarative; trace otherwise |
| `SqlSelectRule` | SELECT | populate the `INTO` list; `SQLCODE = 0` |
| `SqlFetchRule` | FETCH | bounded rows with a runtime counter (§5.5) |
| `SqlCursorLifecycleRule` | OPEN, CLOSE | trace; `OPEN` resets the cursor's state |
| `SqlUpdateRule` | INSERT, UPDATE, DELETE | trace table; `SQLCODE = 0` |
| `SqlSetRule` | SET | give the first host variable a defined value |

`SQLCODE` is **never synthesized** — `EXEC SQL INCLUDE SQLCA` was expanded by the
inliner into ordinary `WORKING-STORAGE`, so the rules move into the field that
is already there. Every `_set_sqlcode` is guarded by
`if "SQLCODE" in ctx.symbols`.

## 5.9 `rules_eib.py` — DFHRESP and the EIB

### DFHRESP substitution

The only in-place substitution in the pipeline. `DFHRESP(NORMAL)` becomes the
numeric condition value from `cics_conditions.json` (119 entries):

```cobol
           IF WS-RESP NOT = DFHRESP(NORMAL)     ->     IF WS-RESP NOT = 0
```

An unmapped condition yields `9999` plus `W-DFHRESP-UNKNOWN`, and the result is
marked `confidence="fallback"`. `9999` is deliberately non-zero, so a
"did this fail?" test keeps behaving as it did.

### EIB synthesis

CICS supplies the EXEC Interface Block at run time; the source declares none of
it. `referenced_eib_fields()` finds `EIB*` names the program *uses* but does not
declare, and only those are emitted — with the PICTURE CICS gives them.

`EIBCALEN` is the one with a semantically loaded value:

```cobol
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
```

It is the length of the commarea, and programs branch on it:

```cobol
           IF EIBCALEN IS EQUAL TO ZERO
               MOVE ' NO COMMAREA RECEIVED' TO EM-VARIABLE
               PERFORM WRITE-ERROR-MESSAGE
               EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC
           END-IF
```

A zero would send every program straight down its "no commarea" abend path,
mocking almost none of the real logic. `9999` — the largest a `PIC S9(4)` field
holds — takes the path the programs are actually written for. (An earlier
`32500` overflowed the picture and drew a compiler warning.)
