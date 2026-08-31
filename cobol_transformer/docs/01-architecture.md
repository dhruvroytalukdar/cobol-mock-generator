# 1. Architecture

## 1.1 The problem

The GenApp corpus is a 31-program IBM insurance sample written for z/OS. None of
it compiles or runs outside a real CICS + DB2 mainframe:

- every program issues `EXEC CICS` commands (LINK, RETURN, SEND MAP, ABEND, …)
- nine programs issue `EXEC SQL` against DB2
- **all file I/O goes through CICS** — `EXEC CICS READ/WRITE/REWRITE FILE(...)`
  against VSAM. There is no native `SELECT`/`FD`/`OPEN` anywhere in the corpus
- programs read CICS pseudo-registers (`EIBCALEN`, `EIBTRNID`) that nothing
  declares, and `DFHCOMMAREA`, which CICS supplies at run time
- copybooks (`COPY`, `EXEC SQL INCLUDE`) are not expanded in the source

The goal: produce, for each program, a **single self-contained `.cbl`** that
compiles under GnuCOBOL and runs to completion, where only the
mainframe-dependent statements have been replaced by mocks, and **every other
line is byte-for-byte the original**.

## 1.2 The eight stages

```
   MAIN.cbl  +  copybooks
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 1. INLINE     text-level copybook expansion                  │
 │               inline/{lexer,scanner,replacing,inliner}       │
 │               discovery/copybook_resolver                    │
 │               ──> expanded_text  (the CANONICAL text)        │
 └──────────────────────────────────────────────────────────────┘
        │  + syntax_repair (punctuation GnuCOBOL requires)
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 2. DETECT     AST via HTTP  ──> classify ──> anchor          │
 │               ast_client/, analysis/{node_classifier,anchor} │
 │               ──> ordered, non-overlapping ReplacementRanges │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 3. TERMINATOR did each statement end its COBOL sentence?     │
 │               rewrite/terminator.py                          │
 │               ──> had_trailing_period, term_end per range    │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 4. MOCK       rule dispatch ──> generated COBOL statements   │
 │               mocks/*  (uses symbol_table, exec_text_parser) │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 5. REWRITE    comment original lines, insert mock below      │
 │               rewrite/{commenter,rewriter}                   │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 6. INJECT     EIB fields, mock counters, LINKAGE promotion   │
 │               rewrite/ws_injector.py                         │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 7. WRITE      .cbl + manifest.json + report.txt              │
 │    VERIFY     reverse the transformation, diff vs. input     │
 └──────────────────────────────────────────────────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ 8. COMPILE    cobc -x  (through WSL on Windows), optional run│
 └──────────────────────────────────────────────────────────────┘
```

`pipeline.run()` is the whole thing in ~200 lines; each stage is a call into a
module that does one job.

## 1.3 The five decisions that shape everything

### Decision 1 — inline copybooks *before* the AST tool runs

The AST **cannot see copybook boundaries**. Two separate blind spots:

- `COPY` produces **no node at all**. The copied data items are silently spliced
  into e.g. `WorkingStorageSection`'s children with zero provenance.
- `EXEC SQL INCLUDE ... END-EXEC` produces **nothing whatsoever** — the text
  falls in a gap between two sibling nodes, invisible even as raw text.

So copybook expansion must be a text pass, and it is done first. The payoff is
that the AST tool then receives one physically complete file, which eliminates
the entire problem class for every later stage instead of working around it
repeatedly. See [Copybook Inlining](02-copybook-inlining.md).

### Decision 2 — one canonical text, and never trust AST line numbers

After inlining and repair, `expanded_text` is fixed and **every offset in the
pipeline indexes into that exact string**. Line endings are normalised to `\n`
once, and never re-normalised.

AST line numbers (`stmtStartLineNumber` and friends) are **never read anywhere**.
They are strings, they drift non-linearly from true physical lines, container
nodes sometimes report `end < start`, and copybook-derived items carry the
*copybook's* line numbers with no marker saying so. The only trustworthy thing
the AST reports positionally is `Source Text`, an exact verbatim substring —
so constructs are located by searching for that text. See
[Anchoring](03-detection-and-anchoring.md#33-anchoring).

### Decision 3 — comment, never delete

The original statement stays in the output, commented out, with the mock
directly below it. This means the transformed file is a complete record of
every change: a reviewer sees what was mocked *and* what replaced it, in place,
without consulting the manifest. It also makes the equivalence proof
straightforward — un-commenting reconstructs the input.

### Decision 4 — mocks must preserve control flow, not just compile

A mock has to return control exactly where the real command did.
`EXEC CICS RETURN` ends the program, so its mock is `GOBACK`; a trace line alone
would let execution fall into code that never previously ran. This extends to
loop termination, where the mock must eventually report "no more data" or a
`PERFORM UNTIL` never ends. See [Mocking](05-mocking.md#54-flow-preservation).

The subtlest case is the **COBOL period**, which terminates a *sentence* and can
close an `IF` scope early. Emitting one where the original had none — or dropping
one — silently changes control flow. Handled in
[Terminator fidelity](06-rewriting.md#61-terminator-fidelity).

### Decision 5 — fail closed, always

Every uncertain situation degrades to something visible rather than something
silently wrong:

| Situation | Behaviour |
|---|---|
| Node's `Source Text` not found at/after the cursor | skip, `E-ANCHOR-NOT-FOUND`, cursor **not** advanced |
| Node found only *before* the cursor | skip, `E-ANCHOR-OUT-OF-ORDER` (document-order assumption broken) |
| Ranges overlap | `E-ANCHOR-OVERLAP`, refuse to emit |
| Live code shares the statement's physical line | skip, `E-COMMENT-LINE-NOT-PURE`, source untouched |
| Option text will not tokenise | generic fallback rule, `W-FALLBACK-RULE-USED` |
| Unmapped CICS condition name | non-zero sentinel `9999`, `W-DFHRESP-UNKNOWN` |
| Copybook not found | hard error by default; `--continue-on-missing-copybook` emits a placeholder |

The reasoning: **an un-mocked construct is a compile error you can see and fix;
a mis-anchored splice silently corrupts working code.** The first is always
preferred.

## 1.4 Data flow, concretely

```python
# pipeline.run(path, options)

inlined  = Inliner(resolver).inline_file(path)      # 1
expanded = normalize_newlines(inlined.text)
expanded = repair(expanded).text                    # punctuation fixes

lexer    = SourceLexer(expanded)                    # shared by later stages
document = HttpAstClient().get_ast(expanded, name)  # 2
detection= anchor_nodes(expanded, document)         #   -> ReplacementRange[]

annotate_terminators(expanded, detection.ranges)    # 3

symbols  = build_symbol_table(expanded, lexer)      # 4
allocator= VarAllocator(symbols)
for rng in detection.ranges:
    ctx  = RuleContext(...)
    rule, result = engine.dispatch(ctx)
    generated[rng.start] = render_statements(...)

rewritten= rewrite(expanded, ranges, generated, inline_text, meta)   # 5
injected = inject(rewritten.text, eib_needed, extra_items=...)       # 6

manifest.constructs = [...]                          # 7 (line numbers shifted)
```

Two details worth noting because they are easy to get wrong:

1. **`lexer` is built once and shared.** The symbol table, paragraph map and
   `PROCEDURE DIVISION` offset all consult the same mask, so "is this offset
   real code?" always gets one consistent answer.

2. **Stage 6 inserts lines, which invalidates the line numbers stage 5
   recorded.** `inject()` returns its insertion points and the manifest shifts
   every recorded line through `injected.shift()`. Getting this wrong is not
   cosmetic — the verifier uses those numbers to reverse the transformation, and
   stale numbers made it un-comment the wrong lines. This was a real bug the
   verifier caught.

## 1.5 Key data structures

**`ReplacementRange`** (`analysis/anchor.py`) — a located, classified span:

```python
start: int              # offset into expanded_text
end: int                # offset just past the construct
term_end: int           # end, extended past its sentence period if it has one
had_trailing_period: bool
node: AstNode | None
category: Category      # CICS | SQL | DFHRESP | EXEC_UNKNOWN
is_statement: bool      # False for sub-expressions substituted in place
source_text: str
```

**`RuleContext`** (`mocks/rule_engine.py`) — everything a rule needs: the parsed
command, symbol table, indent column, terminator flag, whether the construct is
`declarative` (before `PROCEDURE DIVISION`), enclosing paragraph, sequence
number, and the `VarAllocator`.

**`MockResult`** — `statements` (procedural COBOL) *or* `inline_text` (for
sub-expression substitution), plus diagnostics and a `confidence` of
`"high"`/`"fallback"`.

**`TransformationManifest`** — one `ConstructRecord` per construct, recording
where it came from, what rule matched, what was generated, which output lines
hold the comment and which hold the mock, and the final status.

## 1.6 Two structural facts about the corpus that the design relies on

Both were verified across all 31 programs before being depended on:

1. **Every `EXEC` statement occupies its own physical line(s)** — none shares a
   line with unrelated code. This is what makes line-commenting safe. It is not
   *assumed*: `commenter.purity_error()` checks it per statement and fails
   closed if it is ever false.

2. **`LINKAGE SECTION` always follows `WORKING-STORAGE SECTION`, and no program
   has a `PROCEDURE DIVISION USING` clause.** This is what makes LINKAGE
   promotion sound — see
   [Injection](06-rewriting.md#64-making-programs-runnable). `ws_injector`
   checks the ordering and emits `W-LINKAGE-NOT-PROMOTED` rather than proceeding
   if it does not hold.

## 1.7 What is deliberately *not* done

- **No re-parse or reformat step.** Output is produced by splicing into the
  canonical text. Nothing reflows, re-indents or normalises the program, which
  is precisely why unmocked code survives byte-for-byte.
- **No attempt at real pseudo-conversational semantics.** A CICS transaction
  that returns and is re-entered on the next terminal input is modelled as a
  program that simply ends. Documented, not chased.
- **`POINTER` / `ADDRESS OF` are left alone.** GnuCOBOL supports them natively;
  they compile, though runtime semantics differ from Enterprise COBOL.
- **No LINK target execution.** `EXEC CICS LINK PROGRAM(X)` traces and continues
  rather than `CALL`ing X, because X is compiled separately and would not be
  found at run time. LINK returns to its caller, so tracing preserves flow.
