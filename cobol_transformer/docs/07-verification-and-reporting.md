# 7. Verification & Reporting (Stage 7)

Modules: `verify.py`, `output/manifest.py`, `output/writer.py`, `tests/unit/`

## 7.1 The equivalence proof

The central claim is that **only the mocked constructs changed**. That is not
asserted — it is checked mechanically, per program, by reversing the
transformation and diffing against the input.

### The reconstruction

`verify.verify(expanded_text, output_text, manifest)`:

1. **Delete** every line in a construct's `inserted_lines` range — the mocks.
2. **Un-comment** every line in a construct's `commented_lines` range — restore
   column 7 to a space.
3. **Delete** the synthesized declaration block — the banner plus the `01`
   entries following it.
4. **Delete** the LINKAGE promotion notes and **un-comment** the
   `LINKAGE SECTION.` header.
5. Compare line by line against `expanded_text`.

```python
rebuilt = []
for i, line in enumerate(out_lines):
    if i in drop:
        continue
    rebuilt.append(_uncomment(line) if i in uncomment else line)
```

If the reconstruction matches, then by construction every surviving line —
every branch, `PERFORM`, `GO TO`, paragraph, and data item — is exactly what it
was.

### Two categories that need care

**In-place substitutions must not be deleted.** A `DFHRESP` edit sits on a line
that is still live code; its "inserted" span *is* that line:

```python
if c.status == "substituted_in_place":
    continue          # restore it instead, in _is_expected_difference
```

Getting this wrong deleted the whole `IF WS-RESP NOT = DFHRESP(NORMAL)` line
from the reconstruction and reported 12 spurious differences per program.

**Declared differences are recognised, not ignored.** `_is_expected_difference()`
accepts a line only when it differs by something the manifest explicitly
records:

```python
# the PROGRAM-ID repair appends the period COBOL requires
if repaired_program_id and "PROGRAM-ID" in expected.upper():
    return got.rstrip() == expected.rstrip() + "."

# a DFHRESP line matches once the recorded original text is put back
for c in inline_edits:
    restored = got
    for gen in c.generated_text:
        restored = restored.replace(gen, original, 1)
    if restored == expected:
        return True
```

This is a whitelist keyed to manifest entries, not a fuzzy match — an
undeclared change still fails.

### Result

**26 / 26 AST-parsable programs reconstruct byte-identically.** Run it yourself:

```bash
python -m cobol_transformer.cli verify genapp-files/src/lgucvs01.cbl
# lgucvs01.cbl: VERIFIED - 241 lines reconstruct exactly; 13 mocked constructs
```

### What the verifier found during development

It is worth saying that this was not ceremony. The verifier caught two genuine
bugs that compilation and execution both missed:

1. **Stale manifest line numbers.** Stage 6 inserts lines after stage 5 records
   positions, so every recorded line number was off by the injected count.
   Programs still compiled and ran — but the manifest pointed at the wrong lines,
   which would have misled anyone reading a report. Fixed with
   `InjectionResult.shift()`.
2. **Blank-line round-tripping.** Commenting a blank line inside a multi-line
   EXEC added an asterisk that did not reverse cleanly, revealing that blank
   lines should simply be left alone.

## 7.2 The manifest

`output/manifest.py` emits one `ConstructRecord` per construct:

```json
{
  "original_file": "lgicdb01.cbl",
  "original_line": 122,
  "expanded_line_start": 359,
  "expanded_line_end": 359,
  "node_type": "ExecEndExec",
  "category": "cics",
  "verb": "ABEND",
  "raw_text": "EXEC CICS ABEND ABCODE('LGCA') NODUMP END-EXEC",
  "had_trailing_period": false,
  "matched_rule": "cics_abend",
  "confidence": "high",
  "status": "commented_and_mocked",
  "commented_line_start": 366,
  "commented_line_end": 366,
  "inserted_line_start": 367,
  "inserted_line_end": 368,
  "generated_text": [
    "               DISPLAY '>>> MOCK ABEND @MAINLINE: ' 'ABCODE=LGCA'",
    "               GOBACK"
  ],
  "diagnostic_codes": []
}
```

`original_file`/`original_line` come from the source map, so a construct that
arrived via a copybook is traced back to the copybook, not to the expanded file.

Run-level metadata: `detection_backend`, `ast_error`, resolved `copybooks` (with
paths and whether each was synthesized), `synthesized_fields`,
`linkage_promoted`, all `diagnostics`, and — after `build` — the raw `cobc`
output.

The `summary` block is computed:

```json
{
  "constructs": 10,
  "by_status": { "commented_and_mocked": 10 },
  "fallback_rules_used": 0,
  "skipped": 0
}
```

Those last two are the health metrics worth watching: **`fallback_rules_used`
above zero means a verb has no specific rule**, and **`skipped` above zero means
a construct was left untransformed** and will likely fail to compile.

## 7.3 The report

`output/writer.render_report()` renders the same data for humans, grouped and
tabulated:

```
==============================================================================
COBOL transformation report - LGSETUP
==============================================================================
source            : ...\genapp-files\src\lgsetup.cbl
output            : ...\transformed\lgsetup.cbl
detection backend : text-fallback
ast fallback cause: Parse errors in lgsetup.cbl — AST cannot be generated:
linkage promoted  : True

constructs        : 84
by status         : {'commented_and_mocked': 84}
fallback rule use : 0
skipped           : 0

------------------------------------------------------------------------------
  LINE  CAT    VERB             RULE                   P  STATUS
------------------------------------------------------------------------------
   128  cics   RECEIVE          cics_terminal          n  commented_and_mocked
   138  cics   DELETEQ TS       cics_queue             Y  commented_and_mocked
   157  cics   WRITEQ TS        cics_queue             n  commented_and_mocked
```

The `P` column is the terminator flag, which makes terminator handling auditable
at a glance.

## 7.4 The test suite

```
198 passed, 5 skipped
```

| File | Count | Covers |
|---|---|---|
| `test_lexer_and_scanner.py` | 8 | comment/literal masking, EXEC boundaries, COPY and INCLUDE forms |
| `test_terminator_and_commenter.py` | 10 | period detection cases, codegen terminator, column-72 limit, purity check |
| `test_anchor_and_parsers.py` | 16 | duplicate/missing/out-of-order anchoring, CRLF, pruning, CICS + SQL parsing, PICTURE, symbol table |
| `test_inliner_and_rewriter.py` | 13 | REPLACING, nested COPY, cycles, banner column, comment-not-delete, in-place substitution |
| `test_detector_parity.py` | 31 (5 skip) | AST vs. lexer span parity, per program |
| `test_end_to_end.py` | 125 | equivalence, no skips, all mocked lines commented, column limits, determinism |

### The tests that matter most

**Anchoring against duplicates** — proves the monotonic cursor works:

```python
def test_duplicate_statements_anchor_to_distinct_occurrences():
    a = "EXEC CICS ABEND END-EXEC"
    text = f"       {a}\n       MOVE 1 TO X\n       {a}\n"
    res = anchor_nodes(text, _doc(_exec_node(a), _exec_node(a)))
    assert res.ranges[0].start == text.index(a)
    assert res.ranges[1].start == text.rindex(a)
```

**Fail-closed anchoring** — proves a miss is skipped, not guessed:

```python
def test_missing_source_text_fails_closed():
    res = anchor_nodes("       MOVE 1 TO X\n", _doc(_exec_node("EXEC CICS NOPE END-EXEC")))
    assert res.ranges == [] and res.skipped == 1
    assert res.diagnostics[0].code == "E-ANCHOR-NOT-FOUND"
```

**Purity check** — proves shared-line code is never corrupted:

```python
def test_impure_line_is_skipped_rather_than_corrupted():
    text = "       MOVE 1 TO A  EXEC CICS RETURN END-EXEC.\n"
    out = rewrite(text, [rng], {rng.start: ["           GOBACK."]}, {})
    assert out.text == text          # nothing changed at all
    assert out.entries[0].status == "skipped_comment_line_not_pure"
```

**Determinism** — the property golden-file testing depends on:

```python
def test_transformation_is_deterministic():
    assert run(path, OPTS).output_text == run(path, OPTS).output_text
```

**Equivalence, per program** — the headline guarantee, as a parameterised test:

```python
@pytest.mark.parametrize("name", [...])
def test_only_mocked_constructs_differ(transformed, name):
    v = verify(res.expanded_text, res.output_text, res.manifest)
    assert v.ok, "\n".join(v.differences)
```

### Skips are meaningful

The 5 skips are `test_detector_parity` on the programs the language server
declines to parse — the test skips itself rather than failing, because there is
no AST to compare against. Tests needing the AST server skip themselves when it
is not running; the end-to-end tests use `use_ast=False` and need only the
corpus, so the core guarantee is verifiable with no Java at all.
