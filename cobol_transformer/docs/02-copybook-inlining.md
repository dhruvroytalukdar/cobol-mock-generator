# 2. Copybook Inlining (Stage 1)

Modules: `inline/lexer.py`, `inline/scanner.py`, `discovery/copybook_resolver.py`,
`inline/replacing.py`, `inline/inliner.py`, `inline/source_map.py`, `inline/bms.py`

## 2.1 Why this runs first, at the text level

The AST is blind to copybook boundaries in two different ways:

| Form | What the AST shows |
|---|---|
| `COPY LGCMAREA.` | **No node.** Copied data items appear as ordinary children of `WorkingStorageSection` with no provenance marker |
| `EXEC SQL INCLUDE SQLCA END-EXEC.` | **Nothing at all.** The text sits in a gap between two sibling nodes and is invisible even as raw text |

So expansion has to be text-level. Doing it *first* — before the AST tool ever
runs — means the tool receives one physically complete file, and no later stage
ever has to reason about copybooks again.

## 2.2 `inline/lexer.py` — the lexical mask

Everything text-level in this project consults this first. One forward scan
labels **every character offset** with a `Kind`:

```python
class Kind(IntEnum):
    IGNORED = 0   # sequence area (cols 1-6), identification area (73+), line endings
    CODE    = 1   # ordinary program text
    COMMENT = 2   # a fixed-format comment line ('*' or '/' in column 7)
    STRING  = 3   # inside a quoted literal
    EXEC    = 4   # inside EXEC ... END-EXEC
```

This is what stops the scanner matching `COPY` inside a comment or a string
literal. Concretely, all three of these are correctly *ignored*:

```cobol
      * COPY LGCMAREA.                        <- COMMENT
           MOVE 'COPY LGCMAREA.' TO WS-TEXT.  <- STRING
```

### Fixed-format column discipline

COBOL fixed format assigns meaning by column, and the lexer respects it:

| Columns | 0-based | Meaning |
|---|---|---|
| 1–6 | `[0:6]` | sequence number area — ignored |
| 7 | `[6]` | indicator: `*` or `/` = comment, `-` = continuation |
| 8–11 | `[7:11]` | Area A — division/section/paragraph headers |
| 12–72 | `[11:72]` | Area B — statements |
| 73+ | `[72:]` | identification area — ignored |

Only columns 8–72 are ever classified as `CODE`. Text past column 72 is
`IGNORED`, which is correct: the compiler does not read it either.

### String literals

Quote-aware with doubled-quote escaping, so `'IT''S'` is one literal:

```python
if ch == quote:
    if i + 1 < code_stop and text[i + 1] == quote:  # doubled = escaped
        kinds[i + 1] = Kind.STRING
        i += 2
        continue
    in_string = False
```

### EXEC block discovery

After line classification, `_find_exec_blocks()` pairs each `EXEC` with its
`END-EXEC`, searching only over `CODE`-classified offsets. Two subtleties:

```python
# END-EXEC itself contains "EXEC"; skip a match that is part of one.
if start >= 4 and text[start - 4 : start].upper() == "END-":
    continue

# An unterminated EXEC is left as ordinary code rather than swallowing
# the rest of the file.
if not end_m:
    continue
```

Each block yields an `ExecBlock` with `start`, `end`, `dialect`
(`CICS`/`SQL`/`UNKNOWN`, from the second token), the verbatim `text`, and a
`body` — the code-only text with comment lines and out-of-range columns
stripped, so option parsing never sees commentary or sequence numbers.

Finally `_mark_exec_regions()` re-labels `CODE` inside blocks as `EXEC`.
`STRING` and `COMMENT` survive, so a literal inside an EXEC stays a literal.

**Result on the corpus:** 556 EXEC blocks across 31 programs, zero `UNKNOWN`
dialects — matching the counts documented in the design plan (lgsetup 84,
lgwebst5 50).

## 2.3 `inline/scanner.py` — finding COPY and INCLUDE

Both forms are copybook inclusion and are handled identically downstream.

```python
_COPY = re.compile(
    r"\bCOPY\s+(?P<name>[A-Za-z0-9$#@_-]+)"
    r"(?:\s+(?:OF|IN)\s+(?P<lib>[A-Za-z0-9$#@_-]+))?"
    r"(?P<rest>.*?)\.",
    re.IGNORECASE | re.DOTALL,
)
```

`DOTALL` matters: a `COPY ... REPLACING ...` clause may span lines before its
terminating period.

Every match is filtered through the lexer:

```python
if lx.kind_at(start) != Kind.CODE:      # comment or literal - not a statement
    continue
if any(s <= start < e for s, e in include_spans):   # inside an EXEC SQL INCLUDE
    continue
```

`EXEC SQL INCLUDE` is found by walking the lexer's SQL blocks and confirming
`INCLUDE` is the statement *verb* (third token), not a word appearing inside
some other clause. A directly following period is absorbed so the spliced
copybook text is not preceded by a stray terminator.

Results are merged and sorted by offset, so the inliner sees one document-order
list regardless of which form each entry came from.

## 2.4 `discovery/copybook_resolver.py` — finding the text

Search order:

1. each `--copybooks DIR`, in the order given
2. the main program's own directory (matching the flat `genapp-files/src` layout)

Extensions tried per directory: `.cpy`, `.CPY`, `.cbl`, `.CBL`, and the bare
name. Exact matches are tried first, then a case-insensitive directory scan —
necessary because the corpus writes `COPY LGCMAREA.` but ships `lgcmarea.cpy`.

### Two copybooks that do not exist on disk

The corpus references five copybook names; two have no file:

| Name | Referenced by | Resolution |
|---|---|---|
| `LGCMAREA` | 22 programs | `lgcmarea.cpy` |
| `LGPOLICY` | 6 programs | `lgpolicy.cpy` |
| `SQLCA` | 19 includes | **built-in provider** |
| `SSMAP` | 5 menu programs | **generated from `ssmap.bms`** |

**`SQLCA`** is the DB2 communication area. On z/OS the DB2 precompiler injects
it, so no file exists in the source tree. The resolver supplies the standard
layout as `SQLCA_TEXT`. This matters beyond convenience: because `SQLCODE`
becomes an ordinary `WORKING-STORAGE` field, the SQL mocks can simply
`MOVE 0 TO SQLCODE` with **no synthesized declaration at all**.

**`SSMAP`** is the BMS symbolic map — see the next section.

A real file always wins over a built-in provider, so dropping a genuine
`SQLCA.cpy` into the search path overrides the synthetic one.

## 2.5 `inline/bms.py` — generating the symbolic map

The corpus ships `ssmap.bms` (BMS assembler macros) but not the `SSMAP` COBOL
copybook the five menu programs `COPY`. On a mainframe that copybook is produced
by assembling the map with `TYPE=DSECT`. This module does the same
transformation directly.

**Parsing.** BMS statements continue when column 72 is non-blank, with
continuation operands resuming at column 16:

```python
continued = len(raw) > _CONT_COL and raw[_CONT_COL] != " "
body = raw[:_CONT_COL] if continued else raw
buf += body[15:].rstrip()     # continuation operands start in column 16
```

`_operand()` extracts `KEY=value`, handling parenthesised values `POS=(4,50)`
and quoted ones `INITIAL='...'`.

**Generation.** For each named `DFHMDF` field of each `DFHMDI` map, the standard
symbolic-map layout is emitted:

```cobol
       01  SSMAPC1I.
           02  FILLER PIC X(12).            <- TIOAPFX=YES 12-byte prefix
           02  ENT1CNOL    COMP PIC S9(4).  <- length / input data length
           02  ENT1CNOF    PIC X.           <- flag byte
           02  FILLER REDEFINES ENT1CNOF.
               03  ENT1CNOA    PIC X.       <- attribute byte
           02  ENT1CNOI    PIC X(10).       <- input value
       01  SSMAPC1O REDEFINES SSMAPC1I.     <- parallel output view
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).             <- covers L (2 bytes) + F/A (1 byte)
           02  ENT1CNOO    PIC X(10).
```

Unnamed `DFHMDF` fields (screen literals) get no symbolic entry, exactly as the
real expansion behaves.

**Result:** 6 maps, 84 named fields, 616 generated lines. Cross-checked against
what the menu programs actually reference — every referenced symbol is
generated, none missing.

## 2.6 `inline/replacing.py` — COPY ... REPLACING

**No program in the corpus uses `REPLACING`**, so this path is exercised only by
synthetic unit tests. It is implemented for generality and flagged as the
residual risk it is.

Three operand forms:

| Form | Matching |
|---|---|
| `==pseudo text==` | token sequence, tolerant of differing whitespace runs and line breaks |
| `'literal'` | exact |
| `identifier` | whole-word, case-insensitive |

Pseudo-text becomes a whitespace-flexible regex:

```python
return re.compile(r"\s+".join(re.escape(t) for t in body.split()), re.IGNORECASE)
```

Identifiers use lookaround rather than `\b`, because COBOL names contain
hyphens and `\b` would match inside `ABC-DEF`:

```python
rf"(?<![A-Za-z0-9_-]){re.escape(pair.pattern)}(?![A-Za-z0-9_-])"
```

Pairs apply left to right, each scanning **forward past its own replacement**,
so `A BY AA` terminates instead of looping forever.

## 2.7 `inline/inliner.py` — recursive expansion

The core is `_expand()`, which appends the fully expanded form of one text to a
shared output list, recursing per copybook.

### Whole-line spans

This is the detail that took a real bug to get right. A `COPY` statement
occupies its own line(s), and the generated banner comment must start in
column 1 so its `*` lands in the indicator column:

```python
def whole_line_span(start, end):
    first, last = index.lines_spanned(start, end)
    ls, le = index.line_start(first), index.line_end(last)
    if text[ls:start].strip() or text[end:le].strip():
        return start, end          # shares a line with code: leave alone
    return ls, min(le + 1, len(text))
```

Without this, replacing only the `COPY LGPOLICY.` characters left the line's
leading indentation in place, so the banner began at column 18 and the parser
saw garbage. It failed **30 of 31 programs**.

### Cycle detection and duplicate handling

```python
if not book.synthesized and real_path in stack:
    raise CopybookCycleError("COPY cycle detected: " + " -> ".join(stack + [real_path]))
```

Duplicate `COPY`s of the same book are **deliberately not memoized** — each
occurrence is independently re-expanded, matching true COBOL macro semantics
(`REPLACING` may differ per occurrence, and each needs its own source-map entry).

### Fixed-format normalisation

`normalize_fixed_format()` shifts copybook text into columns 8–72 if it starts
in the sequence area. Corpus copybooks are already fixed-format, but a
flush-left or generated copybook would otherwise land in columns 1–7 and be
silently dropped by the compiler.

### Provenance banners

Each expansion is wrapped so the expanded file records where text came from:

```cobol
      * >>> BEGIN COPY LGPOLICY (LGPOLICY.cpy)
      ****************************************************************
      *               COPYBOOK for Policy details                    *
      ...
      * <<< END COPY LGPOLICY
```

### Result on the corpus

All 31 programs expand cleanly, zero warnings:

```
lgacdb01.cbl    328 ->   565 lines   LGCMAREA x1, LGPOLICY x1, SQLCA x1
lgipdb01.cbl   1030 ->  1265 lines   LGCMAREA x1, LGPOLICY x1, SQLCA x1
lgtestp1.cbl    318 ->  1039 lines   LGCMAREA x1, SSMAP x1
lgwebst5.cbl    802 ->   802 lines   (no copybooks)
```

## 2.8 `inline/source_map.py` — provenance

Built in the same walk as the splice. Each `SourceSpan` records the origin file,
the origin line, the copy chain and the occurrence index for one region of the
expanded text. `origin_of(offset)` bisects to the containing span and counts
newlines from the span start:

```python
delta = text.count("\n", span.start, offset)
return (span.origin_file, span.origin_line + delta)
```

This is what lets the manifest say a construct came from `lgicdb01.cbl:122`
rather than only "expanded line 359".

**Used only for diagnostics and traceability — never for correctness-critical
logic.** If the source map were wrong, reports would be misleading, but the
transformation itself would still be correct.
