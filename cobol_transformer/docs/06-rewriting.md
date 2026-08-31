# 6. Rewriting (Stages 3, 5, 6)

Modules: `rewrite/terminator.py`, `commenter.py`, `rewriter.py`,
`ws_injector.py`, `syntax_repair.py`, plus `linetools.py`

## 6.1 Terminator fidelity (Stage 3)

### Why a period is a correctness problem

In COBOL a period terminates a **sentence**, not a statement. Inside an `IF`,
`PERFORM` or `EVALUATE` body it closes that scope. So:

- emitting a period where the original had none **ends the enclosing scope
  early**, and statements that were inside the `IF` fall out of it
- dropping one the original had **swallows the following statements into the
  scope**

Either silently changes control flow while still compiling. The corpus is
genuinely inconsistent — both patterns occur, sometimes in the same paragraph:

```cobol
           ELSE
              EXEC CICS RECEIVE INTO(WS-RECV)
                  LENGTH(WS-RECV-LEN)
              END-EXEC                          <-- no period: sentence continues
              MOVE 'R' To WS-FLAG
           END-IF.

           If WS-FLAG = 'R' Then
             EXEC CICS SEND TEXT FROM(FILLER-X)
              WAIT
             END-EXEC.                          <-- period: ends the IF sentence
```

### The detection

Nothing is inferred. The original's terminator is found structurally:

```python
def scan_forward_period(text, end):
    i = end
    while i < n and text[i] in " \t\r\n":     # ONLY whitespace may intervene
        i += 1
    if i < n and text[i] == ".":
        nxt = text[i + 1] if i + 1 < n else ""
        if not nxt.isdigit():                  # a digit would make it a decimal
            return i + 1
    return end
```

Two rules make this exact:

1. **Only whitespace may separate** the statement from its period. If any other
   token intervenes, the period belongs to a *later* statement. This is what
   distinguishes the two cases above.
2. A digit after the period would make it a decimal point. Unreachable at a
   statement boundary, but rejected explicitly as a regression guard.

When a period is found, `term_end` is extended to include it, so the period is
**commented out with the rest of the statement** instead of being left dangling
as live code after a comment block.

Sub-expression ranges (`DFHRESP`) are skipped — they sit inside a live statement
and have no terminator of their own.

### The reproduction

`codegen.render_statements(statements, indent, terminate_with_period)` puts the
period on the **last** generated statement, and only when the original had one.
The result, from the real output:

```cobol
      *       EXEC CICS RECEIVE INTO(WS-RECV)
      *           LENGTH(WS-RECV-LEN)
      *       END-EXEC
              DISPLAY '>>> MOCK RECEIVE @MAINLINE'
              MOVE 'DUMMY' TO WS-RECV-TRANID
              MOVE 0 TO WS-RESP                 <-- no period, sentence continues
              MOVE 'R' To WS-FLAG
           END-IF.

      *      EXEC CICS SEND TEXT FROM(FILLER-X)
      *       WAIT
      *      END-EXEC.
             DISPLAY '>>> MOCK SEND TEXT @MAINLINE'
             DISPLAY '    DATA: ' FILLER-X.     <-- period restored
```

The `IF`/`ELSE`/`END-IF` structure is untouched in both cases.

## 6.2 `commenter.py` — turning statements inert

### The line-purity check (fail-closed)

Before anything is commented, the statement's first and last lines are checked
for other live code:

```python
before = text[index.line_start(first) : rng.start]
after  = text[rng.term_end : index.line_end(last)]
if before.strip() or after.strip():
    return Diagnostic(code="E-COMMENT-LINE-NOT-PURE", ...)
```

If either side has non-whitespace, the range is **rejected** and the source left
untouched — commenting the line would disable code that is not part of the
construct.

Across the corpus every `EXEC` statement occupies its own lines, so this never
fires. It exists so that a violation is a visible, diagnosable failure rather
than silent corruption. There is a unit test for both outcomes.

### The comment itself

Column 7 is forced to `*`; columns 1–6 and 8+ survive byte-for-byte:

```python
def comment_out(line_text):
    if len(line_text) <= INDICATOR_COL:
        line_text = line_text.ljust(INDICATOR_COL + 1)
        return line_text[:INDICATOR_COL] + "*"
    return line_text[:INDICATOR_COL] + "*" + line_text[INDICATOR_COL + 1:]
```

This is the corpus's own comment convention, so no dialect-specific `*>` inline
syntax is introduced. Continuation lines (indicator `-`) are commented the same
way; their content survives as inert text.

**Blank lines are left exactly as they are:**

```python
lines.append(raw if not raw.strip() else comment_out(raw))
```

A blank line inside a multi-line EXEC is already inert. Commenting it would add
an asterisk that does not round-trip through the verifier, and would clutter the
output for no benefit.

### Multi-line handling

There is no line-count branch anywhere. `lines_spanned(start, term_end)` returns
the first and last physical line the byte range touches, and every line between
is commented — whether that is one line or twenty. `Source Text` already spans
`EXEC`…`END-EXEC` inclusively, so a single range covers the whole construct.

## 6.3 `rewriter.py` — the splice (Stage 5)

One linear pass over the canonical text, ranges in sorted order:

```python
for rng in ordered:
    if not rng.is_statement:                 # DFHRESP: substitute in place
        emit(text[cursor:rng.start]); emit(replacement); cursor = rng.end
        continue

    if purity_error(...):                    # fail closed, source untouched
        continue

    block = build_comment_block(...)
    emit(text[cursor:block_start])           # untouched text, byte for byte
    emit("\n".join(block.lines)); emit("\n") # the commented original
    emit("\n".join(mock_lines)); emit("\n")  # the mock, immediately below
    cursor = block_stop + 1

emit(text[cursor:])                          # the tail
```

Because output is *built by copying*, everything outside a range — comments,
indentation, blank lines, paragraph structure, `GO TO`/`PERFORM`/`IF` logic —
survives exactly. **There is no re-parse or reformat step anywhere in the
pipeline**, which is precisely why the equivalence proof succeeds.

Insertion adds lines rather than substituting bytes, which is fine because
nothing downstream re-indexes by original line number; the manifest recomputes
positions from the *output* text.

Each construct yields a `RewriteEntry` recording status, the generated lines,
and which output lines hold the comment and which hold the mock. Statuses:

| Status | Meaning |
|---|---|
| `commented_and_mocked` | normal case |
| `commented_only` | commented, rule produced nothing (declarative) |
| `substituted_in_place` | DFHRESP |
| `skipped_comment_line_not_pure` | purity check failed, source untouched |
| `skipped_overlap` | defensive; ranges overlapped |

## 6.4 Making programs runnable (Stage 6)

`ws_injector.py` performs the three edits that turn a CICS program into a
standalone one. All are confined to the DATA DIVISION.

### LINKAGE promotion

`DFHCOMMAREA` is declared in `LINKAGE SECTION` and, under CICS, addressed by the
commarea the caller passed. Run standalone there is **no caller**, so those items
have no backing storage and touching them faults.

The fix is one line:

```python
lines[lk_line] = comment_out(lines[lk_line])     # comment "LINKAGE SECTION."
```

Commenting the *header alone* makes the `01` entries that follow continue the
preceding `WORKING-STORAGE SECTION`. Their declarations, order, `REDEFINES` and
group structure are untouched — they simply gain real storage:

```cobol
      * >>> LINKAGE SECTION promoted to WORKING-STORAGE by cobol_transformer:
      * >>> no CICS caller supplies a commarea, so these items need storage.
      *LINKAGE SECTION.

       01  DFHCOMMAREA.
```

This is sound **because of two verified corpus facts**: `LINKAGE SECTION` always
follows `WORKING-STORAGE SECTION`, and no program has a
`PROCEDURE DIVISION USING` clause. Both are checked rather than assumed —
the ordering emits `W-LINKAGE-NOT-PROMOTED` and leaves the section alone if it
does not hold, and a `USING` clause would be stripped with
`W-PROC-USING-REMOVED`.

*Why not `PROCEDURE DIVISION USING DFHCOMMAREA` instead?* Because `cobc -x`
builds a main program that receives no arguments, so the linkage item would be
unallocated and the first reference would segfault.

### Declaration injection

Referenced-but-undeclared EIB fields (§5.9) and mock counters (§5.5) are emitted
under a banner immediately before `PROCEDURE DIVISION`:

```cobol
      * >>> TOOL-GENERATED MOCK SUPPORT FIELDS <<<
       01  EIBTRNID     PIC X(4) VALUE 'GENA'.
       01  EIBTASKN     PIC S9(7) COMP-3 VALUE 1.
       01  EIBCALEN     PIC S9(4) COMP VALUE 9999.
       01  MOCK-FETCH-CNT-4       PIC S9(9) COMP VALUE 0.
       PROCEDURE DIVISION.
```

### Insertions are applied bottom-up and reported

```python
for pos, payload in sorted(pending, key=lambda p: -p[0]):
    lines[pos:pos] = payload
    insertions.append((pos, len(payload)))
```

Descending order keeps every earlier index valid while edits are applied.

Critically, `InjectionResult.shift()` lets callers map a pre-injection line
number to the final text:

```python
def shift(self, line_1based):
    delta = sum(n for pos, n in self.insertions if pos < line_1based)
    return line_1based + delta
```

The manifest passes every recorded line through it. **This was a real bug** —
without it, the line numbers stage 5 recorded were stale by however many lines
injection added, and the verifier un-commented the wrong lines. The verifier is
what caught it.

## 6.5 `syntax_repair.py`

Strictly limited to punctuation the COBOL standard already requires. Nothing
here changes what a program computes.

The corpus needs exactly one repair: **`lgwebst5.cbl` omits the period after its
`PROGRAM-ID` paragraph.**

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LGWEBST5          <-- no period, in the original source
       ENVIRONMENT DIVISION.
```

IBM's compiler tolerates it; GnuCOBOL rejects it with
`syntax error, unexpected ENVIRONMENT`. The period is added and reported as
`W-SYNTAX-REPAIR`, and the verifier knows to expect exactly this one difference.

Repairs run **immediately after inlining, before anything computes an offset**,
so the canonical text every later stage indexes into is already well formed.

## 6.6 `linetools.py` — the positional foundation

Every offset↔line conversion in the project goes through `LineIndex`, which
precomputes newline offsets once and bisects per lookup.

```python
def lines_spanned(self, start, end):
    first = self.line_of(start)
    last  = self.line_of(max(end - 1, start))
    return first, last
```

The `end - 1` is deliberate: an `end` sitting exactly on a line start belongs to
the *previous* line, since a range that ends with the newline has not really
entered the next line. Getting this wrong would comment out one line too many on
every multi-line construct.

Also here: the fixed-format column constants, `comment_out()`,
`is_comment_line()`, `is_continuation_line()`, and `area_b_indent_of()` — which
finds the first non-blank column in Area A/B so a mock lines up with the
statement it replaces.

**AST line-number properties are never read anywhere in the pipeline.** This
module is the single source of positional truth.
