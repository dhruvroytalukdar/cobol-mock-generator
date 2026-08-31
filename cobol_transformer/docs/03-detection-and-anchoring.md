# 3. Detection & Anchoring (Stage 2)

Modules: `ast_client/ast_model.py`, `ast_client/http_client.py`,
`analysis/node_classifier.py`, `analysis/anchor.py`, `analysis/text_detector.py`

This stage answers two questions: **what needs mocking**, and **where exactly is
it in the file**. They are deliberately separate — the AST answers the first,
verbatim text search answers the second.

## 3.1 The AST backend

`com.ibm.zta.cobolast.CobolAstHttpServer` wraps IBM's Z Open Editor language
server and is a **black box** — the jar contains only `.class` files. It needs
Java 21 and the Z Open Editor VS Code extension installed locally.

Two integration surfaces exist; the HTTP server is used because it keeps one
long-lived LSP session, avoiding a multi-second JVM/Equinox boot per program:

```
POST /generate-ast
Content-Type: text/plain
X-Filename: lgicdb01.cbl
<raw COBOL source>

-> { "ok": true, "filePath": "...", "ast": { ... } }
-> { "ok": false, "error": "Parse errors in ..." }        (HTTP 500)
```

`HttpAstClient.get_ast()` raises `AstUnavailableError` on either an HTTP error
or `ok: false`, which is what lets the pipeline fall back cleanly.

### Node shape

```json
{
  "Node": "ExecEndExec",
  "Source Text": "Exec CICS Read File('KSDSCUST')\r\n   Into(...)\r\nEnd-Exec",
  "properties": {
    "stmtStartLineNumber": "173",
    "columnStart": "12",
    "_SqlOrCics": "CICS",
    "embeddedLanguageObject": "Read File('KSDSCUST')   Into(...)   ..."
  },
  "Children": [ ... ]
}
```

This is a full **concrete syntax tree**, not an abstracted one — 2,842 nodes and
89 distinct node types for one ~350-line program, up to 23 levels deep. Even a
single identifier reference costs 4–5 levels.

### Three hard limitations, and what each forces

**Limitation 1 — line numbers are unreliable.** `stmtStartLineNumber` and
friends are strings, drift non-linearly from true physical lines (verified: an
offset that changed from −13 to −17 partway through one file), sometimes report
`end < start` on container nodes, and carry the *copybook's* line numbers for
copied items with no marker. → **Forces anchoring by text search (§3.3).**

**Limitation 2 — EXEC blocks are opaque.** Both dialects produce
`Node: "ExecEndExec"`, discriminated by `properties._SqlOrCics`. The command is
**not semantically parsed**: `embeddedLanguageObject` holds the raw text and
`Children` is only crude word tokenisation — there is no "COMMAREA option" node.
→ **Forces the mini-parser** in
[`exec_text_parser`](04-analysis.md#43-exec-option-parsing), and is also why the
lexical fallback loses nothing (§3.5).

**Limitation 3 — copybooks are invisible.** Handled in
[stage 1](02-copybook-inlining.md).

### The CRLF trap

`Source Text` comes back with `\r\n` **even when the submitted source used bare
`\n`**. A naive `expanded_text.find(source_text)` therefore fails on every
multi-line node. `ast_model.normalize_newlines()` is applied to every node's
text at construction:

```python
def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")
```

This single line is load-bearing. Without it, essentially nothing multi-line
anchors.

## 3.2 `node_classifier.py` — what must not survive verbatim

A small registry of `(name, predicate, category, is_statement)`:

```python
def is_exec_cics(node):    return node.node_type == "ExecEndExec" and node.sql_or_cics == "CICS"
def is_exec_sql(node):     return node.node_type == "ExecEndExec" and node.sql_or_cics == "SQL"
def is_exec_other(node):   return node.node_type == "ExecEndExec" and node.sql_or_cics not in ("CICS","SQL")
def is_dfhresp_macro(node):return node.node_type in ("CicsDFHRESPmacro", "CicsDFHRESP2macro")
```

The `is_statement` flag is the important distinction:

| Category | `is_statement` | Treatment |
|---|---|---|
| `CICS`, `SQL`, `EXEC_UNKNOWN` | `True` | comment the lines out, insert a mock below |
| `DFHRESP` | `False` | substitute **in place**, leave the line live |

`DFHRESP(NORMAL)` appears *inside* an ordinary condition:

```cobol
           IF WS-RESP NOT = DFHRESP(NORMAL)
```

Commenting that line would break the `IF`. So this one construct is a true
character-for-character substitution — the only one in the pipeline.

### Pruning EXEC subtrees

```python
def is_pruned(self, node):
    return node.node_type == "ExecEndExec"
```

`AstDocument.walk(prune=...)` yields a pruned node but does not descend into it.
An `ExecEndExec`'s children are re-tokenisation of the *same span*, so descending
would produce overlapping matches for text already claimed by the parent. There
is a unit test for exactly this.

## 3.3 Anchoring

The algorithm that replaces line numbers entirely.

```python
cursor = 0
for node in document.walk(prune=cls.is_pruned):
    rule = cls.classify(node)
    if rule is None:
        continue
    needle = node.source_text            # already newline-normalised
    idx = text.find(needle, cursor)      # search FORWARD from the cursor
    ...
    ranges.append(ReplacementRange(start=idx, end=idx + matched_len, ...))
    cursor = idx + matched_len           # monotonic advance
```

### Why the monotonic cursor matters

Byte-identical statements are common — two `EXEC CICS ABEND ABCODE('LGV1')`
blocks in one program, for instance. Searching from offset 0 each time would
match both nodes to the *first* occurrence, leaving the second un-mocked and the
first double-mocked. Because nodes are visited in document order and each search
starts where the previous match ended, occurrence *n* matches occurrence *n*.

This rests on one **load-bearing assumption**: that `Children` arrays reflect
physical document order. That is not trusted blindly — it is validated (§3.4).

### The whitespace-tolerant retry

```python
if idx == -1:
    m = _flexible_pattern(needle).search(text, cursor)   # \s+ between tokens
    if m:
        idx, matched_len = m.start(), m.end() - m.start()
```

A second attempt where any whitespace run matches any other, in case the
serializer reflows whitespace inside a construct. Literal text between runs must
still match exactly. In practice this never fires on the corpus — the exact
match always succeeds — but it costs nothing and avoids a needless skip.

### Failing closed

```python
if idx == -1:
    before = text.find(needle, 0, cursor)
    code = "E-ANCHOR-OUT-OF-ORDER" if before != -1 else "E-ANCHOR-NOT-FOUND"
    ...
    result.skipped += 1
    continue          # cursor deliberately NOT advanced
```

The two codes are diagnostically distinct: `OUT-OF-ORDER` means the text exists
but only *before* the cursor, which specifically indicates the document-order
assumption broke. Either way the node is skipped, its source left untouched, and
the cursor left alone so no later node is thrown off by a guess.

## 3.4 The disjointness self-check

```python
def _assert_disjoint(result):
    for a, b in zip(ranges, ranges[1:]):
        if a.end > b.start:
            result.diagnostics.append(Diagnostic(code="E-ANCHOR-OVERLAP", ...))
```

Non-overlap is structurally guaranteed by tree semantics plus the monotonic
cursor — but it is *validated* rather than assumed, because the whole splice
depends on it and the cost is one linear pass.

### Empirical validation on the corpus

Across the 26 AST-parsable programs, **406 anchored ranges, zero failures**:

```
lgacdb01     ast_exec=16  lex_exec=16  dfhresp=1   skipped=0  spans_equal=True
lgapdb01     ast_exec=28  lex_exec=28  dfhresp=0   skipped=0  spans_equal=True
lgipdb01     ast_exec=25  lex_exec=25  dfhresp=0   skipped=0  spans_equal=True
lgwebst5     ast_exec=50  lex_exec=50  dfhresp=1   skipped=0  spans_equal=True
...
files=26  ranges=406  skipped=0
```

## 3.5 The fallback, and why it is trustworthy

The Z Open Editor language server **refuses to emit an AST at all** when its
*CICS validator* objects to a command:

```
lgstsq.cbl:114:24: Error: The option "TERMINAL" is required if the option "WAIT" is used.
Exception in thread "main" java.lang.RuntimeException: Parse errors — AST cannot be generated
```

That is a validation opinion, not a parse failure — the statement is perfectly
well-formed COBOL and perfectly mockable. Five programs hit it: `lgicvs01`,
`lgipvs01`, `lgsetup`, `lgstsq`, `lgtestc1` (`SEND TEXT ... WAIT` or `ASIS`
without `TERMINAL`). There is no flag to downgrade it.

`analysis/text_detector.py` produces the **same `ReplacementRange` objects** from
the lexer's EXEC blocks plus a regex for `DFHRESP`, wrapping each in a synthetic
`AstNode` so every downstream stage is path-agnostic.

Two things make this defensible rather than a hack:

1. **The AST contributes nothing extra here.** Per Limitation 2, an EXEC block's
   body arrives as unparsed raw text either way — the AST supplies only the span
   boundaries, and the lexer computes those directly.

2. **Parity is asserted, not assumed.** On all 26 programs where both paths run,
   the AST-anchored EXEC spans are **byte-identical** to the lexer's spans. This
   is a test, `tests/unit/test_detector_parity.py`, parameterised over the whole
   corpus:

```python
ast_spans  = sorted((r.start, r.end) for r in ast_res.ranges if r.category in EXEC_CATEGORIES)
text_spans = sorted((r.start, r.end) for r in detect_by_text(text).ranges if ...)
assert ast_spans == text_spans
```

The five AST-refused programs are **out of scope for the current deliverable**
(see [README](README.md)); the fallback exists so they are not left unhandled,
and the parity evidence is what justifies trusting it when it is used.

## 3.6 Where each stage's information comes from

A useful summary when explaining the design, because "AST-driven" is easy to
overstate:

| Information | Source | Why |
|---|---|---|
| Which constructs need mocking | **AST** node type | unambiguous; immune to formatting |
| Where the construct is | **verbatim text search** | AST line numbers are unreliable |
| What is *inside* the construct | **mini-parser** over raw text | AST does not parse EXEC bodies |
| Data item names, PICTUREs, groups | **text scan** of DATA DIVISION | needed on both paths; strictly regular in fixed format |
| Copybook boundaries | **text scan** | invisible to the AST |
| Sentence terminators | **text scan** forward from the span | not represented as a node |

The AST is used exactly where it is authoritative, and no further.
