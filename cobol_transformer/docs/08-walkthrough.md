# 8. End-to-End Walkthrough

One real program traced through all eight stages, with actual output. Follow
along:

```bash
python -m cobol_transformer.cli detect    genapp-files/src/lgicdb01.cbl
python -m cobol_transformer.cli transform genapp-files/src/lgicdb01.cbl -o out.cbl
python -m cobol_transformer.cli verify    genapp-files/src/lgicdb01.cbl
```

**Subject:** `lgicdb01.cbl` — "inquire customer, DB2 tier". 245 lines, 10
constructs to mock, small enough to read end to end.

---

## Stage 1 — Inline copybooks

The source contains three inclusions, all in the `EXEC SQL INCLUDE` form —
which, remember, is **completely invisible to the AST**:

```cobol
           EXEC SQL
               INCLUDE SQLCA
           END-EXEC.
...
       LINKAGE SECTION.

       01  DFHCOMMAREA.
           EXEC SQL
             INCLUDE LGCMAREA
           END-EXEC.
```

The scanner finds all three over the lexer mask; the resolver locates two on
disk and supplies the third from a built-in:

```json
"copybooks": {
  "LGPOLICY": { "occurrences": 1, "path": "...\\LGPOLICY.cpy", "synthesized": false },
  "LGCMAREA": { "occurrences": 1, "path": "...\\LGCMAREA.cpy", "synthesized": false },
  "SQLCA":    { "occurrences": 1, "path": "<builtin:SQLCA>",   "synthesized": true  }
}
```

Each expansion is wrapped in provenance banners, whose `*` lands in column 7
because the whole `COPY` line is replaced, not just its characters:

```cobol
      * >>> BEGIN EXEC_SQL_INCLUDE SQLCA (<builtin:SQLCA>)
      *****************************************************************
      * SQLCA - DB2 SQL communication area (standard layout).         *
      *****************************************************************
       01  SQLCA.
           05  SQLCAID            PIC X(8).
           05  SQLCODE            PIC S9(9) COMP-5.
           ...
      * <<< END EXEC_SQL_INCLUDE SQLCA
```

**245 → 482 lines.** `expanded_text` is now the canonical text; every offset
from here on indexes into it.

Note the consequence: `SQLCODE` is now an **ordinary WORKING-STORAGE field**, so
the SQL mocks will `MOVE 0 TO SQLCODE` with no synthesized declaration.

`syntax_repair` runs and finds nothing to fix — `lgicdb01` has its `PROGRAM-ID`
period.

---

## Stage 2 — Detect and anchor

`expanded_text` is POSTed to the AST server, which returns a tree. The walker
descends it, classifying and pruning:

```
backend=ast  constructs=10  fallback=0  skipped=0
```

| Line | Category | Verb | Node type |
|---|---|---|---|
| 359 | cics | ABEND | `ExecEndExec` |
| 379 | cics | RETURN | `ExecEndExec` |
| 398 | cics | RETURN | `ExecEndExec` |
| 406 | sql | SELECT | `ExecEndExec` |
| 439 | cics | RETURN | `ExecEndExec` |
| 453 | cics | ASKTIME | `ExecEndExec` |
| 455 | cics | FORMATTIME | `ExecEndExec` |
| 462 | cics | LINK | `ExecEndExec` |
| 470 | cics | LINK | `ExecEndExec` |
| 476 | cics | LINK | `ExecEndExec` |

Note there are **three `EXEC CICS RETURN` statements, and all three are
byte-identical**. This is exactly the case the monotonic cursor exists for: each
search starts where the previous match ended, so occurrence 1 anchors at 379,
occurrence 2 at 398 and occurrence 3 at 439 — instead of all three collapsing
onto the first, which would leave two of them un-mocked and still in the
compiled program.

The disjointness self-check passes; no `E-ANCHOR-*` diagnostics.

---

## Stage 3 — Terminators

Each range is scanned forward past whitespace only:

| Line | Verb | `had_trailing_period` | Consequence |
|---|---|---|---|
| 359 | ABEND | `False` | inside an `IF`, sentence continues |
| 398 | RETURN | `True` | ends its sentence |
| 406 | SELECT | `True` | ends its sentence |
| 462 | LINK | `True` | ends its sentence |
| 470 | LINK | `False` | another statement follows in the same sentence |

Five of ten carry a period, five do not — in one 245-line program. This is why
the terminator cannot be standardised.

---

## Stage 4 — Generate mocks

The symbol table is built (from the expanded text, so it includes every copybook
field), and each construct is dispatched.

### The ABEND at line 359

```cobol
           IF EIBCALEN IS EQUAL TO ZERO
               MOVE ' NO COMMAREA RECEIVED' TO EM-VARIABLE
               PERFORM WRITE-ERROR-MESSAGE
               EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC
           END-IF
```

`AbendRule` matches. `literal_of("'LGCA'")` → `LGCA`. ABEND terminates the
program, so the mock must too:

```python
out = [trace(ctx, cobol_string_literal("ABCODE=LGCA")), "GOBACK"]
```

`had_trailing_period` is `False`, so **no period is emitted** — which is what
keeps the `IF`/`END-IF` intact.

### The SELECT at line 406

`_parse_sql` extracts `_TABLE=CUSTOMER` and an `_INTO` list of nine host
variables. `SqlSelectRule` populates each per its own PICTURE and reports
success.

---

## Stage 5 — Comment and insert

The ABEND, in the final output:

```cobol
           IF EIBCALEN IS EQUAL TO ZERO
               MOVE ' NO COMMAREA RECEIVED' TO EM-VARIABLE
               PERFORM WRITE-ERROR-MESSAGE
      *        EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC
               DISPLAY '>>> MOCK ABEND @MAINLINE: ' 'ABCODE=LGCA'
               GOBACK
           END-IF
```

Everything worth checking is visible here:

- the original is **commented, not deleted** — `*` in column 7, text intact
- the mock sits **immediately below**, at the same Area B column
- **no period**, so the `IF` scope is unchanged
- the surrounding `IF`, `MOVE` and `PERFORM` lines are **byte-identical**
- `GOBACK` preserves "this statement ends the program"

The SELECT, in the final output:

```cobol
      *    EXEC SQL
      *        SELECT FIRSTNAME,
      *               LASTNAME,
      *               DATEOFBIRTH,
      *               ...
      *        INTO  :CA-FIRST-NAME,
      *              :CA-LAST-NAME,
      *              ...
      *        FROM CUSTOMER
      *        WHERE CUSTOMERNUMBER = :DB2-CUSTOMERNUMBER-INT
      *    END-EXEC.
           DISPLAY '>>> MOCK SELECT @GET-CUSTOMER-INFO: '
               'TABLE=CUSTOMER'
           MOVE 'DUMMY' TO CA-FIRST-NAME
           MOVE 'DUMMY' TO CA-LAST-NAME
           MOVE '2024-01-01' TO CA-DOB
           MOVE 'DUMMY' TO CA-HOUSE-NAME
           MOVE 'DUMM' TO CA-HOUSE-NUM
           MOVE 'DUMMY' TO CA-POSTCODE
           MOVE 'DUMMY' TO CA-PHONE-MOBILE
           MOVE 'DUMMY' TO CA-PHONE-HOME
           MOVE 'DUMMY' TO CA-EMAIL-ADDRESS
           MOVE 0 TO SQLCODE.

           Evaluate SQLCODE
             When 0
               MOVE '00' TO CA-RETURN-CODE
             When 100
               MOVE '01' TO CA-RETURN-CODE
```

Four details worth pointing out:

1. A **21-line** EXEC block is commented; no special multi-line handling exists.
2. **`MOVE '2024-01-01' TO CA-DOB`** — the name heuristic recognised a date field.
3. **`MOVE 'DUMM' TO CA-HOUSE-NUM`** — truncated to 4 characters because
   `CA-HOUSE-NUM` is `PIC X(4)`. The PICTURE was consulted per field.
4. **`MOVE 0 TO SQLCODE.`** carries the period, restoring the sentence boundary
   the original `END-EXEC.` had — and the `Evaluate SQLCODE` immediately below
   then works exactly as written, taking the `When 0` branch.

That last point is the whole design in miniature: the business logic that reads
`SQLCODE` is untouched, and it behaves correctly because the mock set the value
the real statement would have.

The `DISPLAY` wrapping onto a continuation line at a deeper indent is
`codegen._wrap` keeping within column 72.

---

## Stage 6 — Inject declarations

The program references four EIB fields it never declares, and has a
`LINKAGE SECTION`:

```json
"synthesized_fields": ["EIBTRNID", "EIBTASKN", "EIBTRMID", "EIBCALEN"],
"linkage_promoted": true
```

LINKAGE promotion — one commented line converts the entries below it into
WORKING-STORAGE:

```cobol
      * >>> LINKAGE SECTION promoted to WORKING-STORAGE by cobol_transformer:
      * >>> no CICS caller supplies a commarea, so these items need storage.
      *LINKAGE SECTION.

       01  DFHCOMMAREA.
```

And the support block, immediately before `PROCEDURE DIVISION`:

```cobol
      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<
       01  EIBTRNID     PIC X(4) VALUE 'GENA'.
       01  EIBTASKN     PIC S9(7) COMP-3 VALUE 1.
       01  EIBTRMID     PIC X(4) VALUE 'TRM1'.
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
       PROCEDURE DIVISION.
```

`EIBCALEN = 9999` is what makes the `IF EIBCALEN IS EQUAL TO ZERO` check from
stage 4 take the **normal** path rather than the abend path — so the program
exercises its real logic instead of dying at the first branch.

These insertions shift line numbers, so every manifest position is passed
through `injected.shift()`.

---

## Stage 7 — Write and verify

```
transformed/lgicdb01.cbl            518 lines
transformed/lgicdb01.manifest.json
transformed/lgicdb01.report.txt
```

```bash
$ python -m cobol_transformer.cli verify genapp-files/src/lgicdb01.cbl
lgicdb01.cbl: VERIFIED - 483 lines reconstruct exactly; 10 mocked constructs
```

The verifier deleted the 10 mock insertions, un-commented the 10 constructs,
removed the 4 EIB declarations and the LINKAGE notes, un-commented the LINKAGE
header — and got back the expanded text, byte for byte.

---

## Stage 8 — Compile and run

```
lgicdb01      245   518 ast   10 mocks   0 fallback   0 skipped   OK   OK   ok
```

```bash
$ cobc -x -std=default -o lgicdb01 lgicdb01.cbl     # exit 0
$ ./lgicdb01
>>> MOCK SELECT @GET-CUSTOMER-INFO: TABLE=CUSTOMER
>>> MOCK RETURN @MAINLINE-END
```

**Only two of the ten mocks executed** — and that is the most informative thing
in the whole walkthrough.

The program mocked 10 constructs, but the run reached just 2. The other eight
live on paths this execution never took:

- the `ABEND` at 359 is behind `IF EIBCALEN IS EQUAL TO ZERO`, and `EIBCALEN`
  was synthesized as 9999, so the check is false
- the `ASKTIME`, `FORMATTIME` and three `LINK`s are inside
  `WRITE-ERROR-MESSAGE`, which is only performed on an error path — and the
  mocked `SELECT` returned `SQLCODE = 0`, so `Evaluate SQLCODE` took `When 0`
- two of the three `RETURN`s are on branches not taken

That is exactly the mainframe control flow for a **successful customer
inquiry**: read the customer, set return code `'00'`, return. If the mocks had
merely been made to compile — or if a terminator had been misplaced and collapsed
an `IF` — the program would have walked a different path and the trace would
show it.

The trace is short because the logic still works, not because it was bypassed.

---

## Summary of the transformation

| | Before | After |
|---|---|---|
| Lines | 245 | 518 |
| Self-contained | no (3 copybooks) | yes |
| Compiles under GnuCOBOL | no | yes |
| Runs | no | yes |
| Constructs mocked | — | 10 |
| Non-mocked lines changed | — | **0** |
