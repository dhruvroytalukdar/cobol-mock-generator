# COBOL Stub Generator

## Overview

This project converts a COBOL program that depends on DB2, CICS, external files, queues, or other runtime resources into a locally runnable COBOL stub.

The generated program preserves the original business-control flow while replacing external operations with deterministic local behavior:

- Database reads populate host variables using meaningful fixtures.
- Database writes display the values that would have been written.
- CICS calls display the target program and commarea.
- File reads populate record fields from fixtures.
- File writes display the record values.
- Counters return deterministic values.
- External status codes are set consistently.
- Missing or ambiguous dependencies are reported instead of being replaced randomly.

The original COBOL file must never be overwritten by default.

The recommended architecture is a deterministic AST-driven transformation pipeline. LangChain or LangGraph are optional and should not be required for the first implementation.

---

## Example input

COBOL source:

```text
C:\Users\dhruv\Desktop\IIT-Kanpur\IBM\cobol-ast-generator-java-cli\cobol-ast-generator-java-cli\lgacdb01\cobol\LGACDB01.cbl
```

AST:

```text
C:\Users\dhruv\Desktop\IIT-Kanpur\IBM\cobol-ast-generator-java-cli\cobol-ast-generator-java-cli\ast\out.json
```

Generated output:

```text
LGACDB01.stub.cbl
LGACDB01.manifest.json
LGACDB01.report.md
fixtures.yaml
```

---

## Main design principle

The AST must be the source of truth for identifying resource statements.

Do not search the complete COBOL file with regular expressions. Regex can incorrectly match:

- Comments.
- String literals.
- Paragraph names containing words such as `WRITE`.
- Nested statements.
- Statements inside unrelated constructs.
- Text that is not executable COBOL.

The generator should use:

1. AST node types.
2. AST source positions.
3. Embedded statement payloads.
4. Symbol-table information.
5. Parent and child relationships.
6. Exact source-span validation.

An LLM may help classify unfamiliar operations, but it should never directly rewrite arbitrary COBOL source.

---

## What the sample AST contains

The supplied AST is a JSON tree rooted at `CompilationUnit`.

Important node types found in the sample include:

- `CompilationUnit`
- `CobolSourceProgram`
- `DataDivision`
- `WorkingStorageSection`
- `LinkageSection`
- `ProcedureDivision0`
- `ExecEndExec`
- `SqlOrCics`
- `StatementList`
- `IfStatement`
- `MoveStatement0`
- `InitializeStatement0`
- `SetStatement1`
- `Perform`
- `Paragraph0`
- `SectionHeader0`

Embedded SQL and CICS blocks are represented by `ExecEndExec` nodes.

An `ExecEndExec` node contains information similar to:

```json
{
  "Node": "ExecEndExec",
  "Source Text": "EXEC CICS GET COUNTER(...) END-EXEC",
  "properties": {
    "stmtStartLineNumber": "225",
    "stmtEndLineNumber": "231",
    "columnStart": "12",
    "columnEnd": "19",
    "_SqlOrCics": "CICS",
    "embeddedLanguageObject": "GET COUNTER(...)"
  }
}
```

The AST includes approximately 25 SQL/CICS execution blocks in the sample program.

The generator should use the complete `ExecEndExec` span, from `EXEC` through `END-EXEC`, when replacing a resource statement.

The AST line numbers must not automatically be assumed to equal physical source-file line numbers. The parser may normalize source text or omit some content. Every AST span must therefore be resolved and verified against the original source before editing.

---

## High-level architecture

```text
COBOL source
     +
AST JSON
     +
copybooks
     +
dialect configuration
     +
fixtures
     |
     v
AST adapter
     |
     v
source-span resolver
     |
     v
resource-operation extractor
     |
     v
normalized operation IR
     |
     +-------------------------+
     |                         |
     v                         v
deterministic rule engine   optional LLM advisor
     |                         |
     +-------------------------+
                 |
                 v
transformation plan
                 |
                 v
declaration planner
                 |
                 v
source-preserving rewriter
                 |
                 v
generated COBOL stub
                 |
                 v
reparse -> compile -> run scenarios -> report
```

---

## Pipeline stages

### 1. Load inputs

The tool loads:

- Original COBOL source.
- AST JSON.
- Parser version.
- Copybooks.
- Compiler/dialect profile.
- Transformation policy.
- Fixture configuration.

The original source should be read using an explicit encoding and line-ending policy.

### 2. Adapt the AST

The AST adapter converts parser-specific JSON nodes into a stable internal representation:

```python
class AstNode:
    kind: str
    source_text: str
    start_line: int | None
    end_line: int | None
    start_column: int | None
    end_column: int | None
    properties: dict
    children: list
```

The rest of the application should not depend directly on parser-specific property names.

### 3. Resolve source spans

Every candidate resource operation must be mapped to an exact character range in the original source:

```text
[start_offset, end_offset)
```

The resolver should:

1. Read the original source.
2. Use AST line and column metadata as a candidate position.
3. Compare the candidate text with the AST node's source text.
4. Normalize only approved differences such as line endings and whitespace.
5. Require one unique match.
6. Store the source offsets and original text hash.

Example edit record:

```json
{
  "operation_id": "op-0017",
  "start_offset": 8120,
  "end_offset": 8298,
  "original_sha256": "...",
  "replacement": "...",
  "rule_id": "cics.get-counter.v1"
}
```

If a unique span cannot be found, the generator must stop or mark the operation as unsupported. It must not guess.

### 4. Extract resource operations

The extractor walks the AST recursively and produces a normalized intermediate representation.

Example:

```json
{
  "id": "op-0017",
  "kind": "CICS",
  "operation": "GET_COUNTER",
  "paragraph": "OBTAIN-CUSTOMER-NUMBER",
  "reads": [
    "GENACOUNT",
    "GENAPOOL"
  ],
  "writes": [
    "LASTCUSTNUM",
    "WS-RESP"
  ],
  "status_targets": [
    "WS-RESP"
  ],
  "source_span": {
    "start_line": 225,
    "end_line": 231,
    "start_offset": 8120,
    "end_offset": 8298
  },
  "enclosing_conditions": [
    "WS-RESP NOT = DFHRESP(NORMAL)"
  ],
  "confidence": "HIGH"
}
```

This intermediate representation is the boundary between analysis and generation.

---

## Supported resource categories

### SQL

Initial SQL support should include:

- `SELECT ... INTO`
- `INSERT`
- `UPDATE`
- `DELETE`
- `MERGE`
- `SET :host-variable = ...`
- `EXEC SQL INCLUDE SQLCA`
- SQL cursor operations
- SQL status handling

### CICS

Initial CICS support should include:

- `LINK`
- `RETURN`
- `ABEND`
- `GET COUNTER`
- `ASKTIME`
- `FORMATTIME`
- CICS include statements
- Common EIB fields
- `DFHRESP(...)` macros

### File I/O

Support should eventually include:

- `SELECT`
- `OPEN`
- `CLOSE`
- `READ`
- `WRITE`
- `REWRITE`
- `DELETE`
- Sequential file status
- Indexed-file keys
- `AT END`
- `INVALID KEY`

### Other operations

The rule registry should later support:

- `CALL`
- MQ operations
- IMS operations
- VSAM operations
- Terminal input/output
- Vendor-specific `EXEC` blocks
- External service calls

Unknown operations must be reported explicitly.

---

## Intermediate operation model

Every operation should contain:

```json
{
  "id": "op-0001",
  "kind": "SQL",
  "operation": "INSERT",
  "source_span": {},
  "paragraph": "INSERT-CUSTOMER",
  "inputs": [],
  "outputs": [],
  "status_targets": [],
  "enclosing_conditions": [],
  "fixture_key": null,
  "rule_id": "sql.insert.v1",
  "confidence": "HIGH",
  "assumptions": [],
  "diagnostics": []
}
```

The operation model allows the generator to:

- Explain what it found.
- Select a deterministic rule.
- Ask an LLM about only one operation.
- Validate generated symbols.
- Produce an audit report.
- Test the transformation independently.

---

## Deterministic rule registry

Each transformation rule should be versioned.

Example rule:

```text
sql.select-into.v1
sql.insert.v1
sql.update.v1
cics.get-counter.v1
cics.link.v1
cics.return.v1
cics.abend.v1
file.read.v1
file.write.v1
```

Each rule should define:

- Required AST evidence.
- Supported compiler dialects.
- Input symbols.
- Output symbols.
- Status variables.
- Success values.
- Error values.
- Fixture requirements.
- Generated declarations.
- Replacement emitter.
- Validation checks.

The first version should use deterministic Python functions rather than LLM-generated COBOL templates.

---

# Semantic replacement rules

## SQL `SELECT ... INTO`

A database read must populate the same host variables that the original SQL statement would populate.

Original:

```cobol
           EXEC SQL
             SELECT CUSTOMER_NUMBER, STATUS
               INTO :WS-CUSTOMER-NUM, :WS-CUSTOMER-STATUS
               FROM CUSTOMER
              WHERE POLICY_NUMBER = :WS-POLICY-NUM
           END-EXEC
```

Generated stub:

```cobol
           MOVE 100001 TO WS-CUSTOMER-NUM
           MOVE 'ACTIVE' TO WS-CUSTOMER-STATUS
           MOVE 0 TO SQLCODE
           DISPLAY '[STUB][SQL SELECT] CUSTOMER'
```

Fixture selection should use:

1. Exact operation fixture.
2. Input predicate or key.
3. Named default fixture.
4. Diagnostic if no meaningful value exists.

The generator should not assign random values.

## SQL `INSERT`

An insert has no normal result row, but its input values are meaningful.

Generated example:

```cobol
           DISPLAY '[STUB][SQL INSERT] CUSTOMER'
           DISPLAY '  CUSTOMER_NUMBER=' DB2-CUSTOMERNUM-INT
           DISPLAY '  FIRSTNAME=' CA-FIRST-NAME
           DISPLAY '  LASTNAME=' CA-LAST-NAME
           MOVE 0 TO SQLCODE
```

Sensitive values must be masked:

```cobol
           DISPLAY '  PASSWORD=[MASKED]'
```

The original program's `SQLCODE` checks must remain valid.

## SQL `UPDATE`, `DELETE`, and `MERGE`

Generated behavior:

```cobol
           DISPLAY '[STUB][SQL UPDATE] CUSTOMER'
           MOVE 0 TO SQLCODE
```

If the source checks the affected-row count, set a deterministic row count such as one:

```cobol
           MOVE 1 TO SQLERRD(3)
```

The exact SQLCA representation must match the selected compiler and local compatibility declaration.

## SQL identity retrieval

For:

```cobol
EXEC SQL
    SET :DB2-CUSTOMERNUM-INT = IDENTITY_VAL_LOCAL()
END-EXEC
```

Generate a deterministic identity value:

```cobol
           MOVE 100001 TO DB2-CUSTOMERNUM-INT
           MOVE 0 TO SQLCODE
```

The value should come from fixture configuration or a deterministic sequence.

## SQL includes

`EXEC SQL INCLUDE SQLCA` is a compile-time dependency.

The generator should:

1. Use a configured local SQLCA copybook if available.
2. Otherwise generate only the SQLCA symbols referenced by the source.
3. Initialize those symbols during each SQL stub.
4. Preserve names such as `SQLCODE`, `SQLSTATE`, and `SQLERRD`.

Do not simply delete SQLCA if the program references `SQLCODE`.

---

## CICS `GET COUNTER`

Original:

```cobol
           EXEC CICS GET COUNTER(GENACOUNT)
                POOL(GENAPOOL)
                VALUE(LASTCUSTNUM)
                RESP(WS-RESP)
           END-EXEC
```

Generated stub:

```cobol
           ADD 1 TO STUB-CICS-COUNTER
           MOVE STUB-CICS-COUNTER TO LASTCUSTNUM
           MOVE 0 TO WS-RESP
```

The counter should be deterministic:

```cobol
       01 STUB-CICS-COUNTER PIC S9(9) COMP VALUE 100000.
```

If the source checks:

```cobol
IF WS-RESP NOT = DFHRESP(NORMAL)
```

the generator must replace or locally define the response macro.

---

## CICS `LINK`

Original:

```cobol
           EXEC CICS LINK PROGRAM(LGACDB02)
                COMMAREA(CDB2AREA)
                LENGTH(32500)
           END-EXEC
```

Generated stub:

```cobol
           DISPLAY '[STUB][CICS LINK] PROGRAM=LGACDB02'
           DISPLAY '[STUB][CICS LINK] COMMAREA=CDB2AREA'
           MOVE 0 TO CA-RETURN-CODE
```

The generator should not invent arbitrary values for the called program's output area unless a fixture explicitly defines them.

For configured responses:

```yaml
cics:
  links:
    LGACDB02:
      return_code: '00'
      values:
        D2-RETURN-CODE: '00'
```

---

## CICS `RETURN`

`EXEC CICS RETURN` affects program termination and cannot always be replaced with a no-op.

Supported policies:

```yaml
return_behavior:
  cics_return: goback
```

Possible choices:

- `GOBACK`: closest to a top-level transaction return.
- `CONTINUE`: useful for exploratory testing.
- `STOP-PARAGRAPH`: useful when generated wrappers are used.

The chosen behavior must be recorded in the manifest.

---

## CICS `ABEND`

Generated example:

```cobol
           DISPLAY '[STUB][CICS ABEND] ABCODE=LGCA'
           GOBACK
```

An optional exploratory mode may continue after the ABEND, but that must be clearly marked as behaviorally different from production.

---

## CICS `ASKTIME` and `FORMATTIME`

Use deterministic clock fixtures by default:

```yaml
clock:
  date: '08252026'
  time: '14301500'
```

Generated values must respect the destination PIC and the requested format.

A real local clock may be supported as an opt-in mode, but deterministic fixtures are preferable for testing.

---

## CICS runtime fields

CICS programs may reference runtime-provided fields such as:

- `EIBCALEN`
- `EIBTRNID`
- `EIBTRMID`
- `EIBTASKN`
- `DFHCOMMAREA`
- `DFHRESP(NORMAL)`

The generator should add local compatibility declarations only for symbols that are:

- Referenced by the source.
- Not already declared.
- Not resolvable from a copybook.

Example:

```cobol
       01 STUB-EIBCALEN PIC S9(4) COMP VALUE 225.
       01 STUB-EIBTRNID PIC X(4) VALUE 'STUB'.
       01 STUB-EIBTRMID PIC X(4) VALUE 'TERM'.
       01 STUB-EIBTASKN PIC 9(7) VALUE 1.
       01 STUB-RESP-NORMAL PIC S9(8) COMP VALUE 0.
```

The generator may need either aliases or AST-based reference rewriting so that the original names resolve locally.

---

## File `OPEN`

Generated example:

```cobol
           MOVE '00' TO CUSTOMER-FILE-STATUS
           DISPLAY '[STUB][FILE OPEN] CUSTOMER-FILE MODE=INPUT'
```

The operation should not access a real external file unless a local fixture file is explicitly configured.

## File `READ`

A file read must populate the record structure.

Example:

```cobol
           MOVE 100001 TO CUSTOMER-NUMBER
           MOVE 'Ada' TO CUSTOMER-FIRST-NAME
           MOVE 'Lovelace' TO CUSTOMER-LAST-NAME
           MOVE '00' TO CUSTOMER-FILE-STATUS
```

For subsequent reads, the fixture must support EOF:

```yaml
files:
  CUSTOMER-FILE:
    records:
      - CUSTOMER-NUMBER: 100001
        CUSTOMER-FIRST-NAME: 'Ada'
        CUSTOMER-LAST-NAME: 'Lovelace'
    end_of_file_after: 1
```

When the fixture is exhausted, set the appropriate file status and allow the original `AT END` branch to execute.

If the record layout cannot be resolved from an FD, copybook, or explicit schema, fail with a diagnostic instead of generating random bytes.

## File `WRITE`, `REWRITE`, and `DELETE`

Generated behavior:

```cobol
           DISPLAY '[STUB][FILE WRITE] CUSTOMER-FILE'
           DISPLAY '  CUSTOMER-NUMBER=' CUSTOMER-NUMBER
           MOVE '00' TO CUSTOMER-FILE-STATUS
```

Sensitive fields should be masked.

---

## Meaningful fixtures

Fixtures should be explicit and reproducible.

Example:

```yaml
program: LGACDB01
scenario: happy-path

clock:
  date: '08252026'
  time: '14301500'

cics:
  counters:
    GENA:GENACUSTNUM:
      values: [100001, 100002, 100003]

  links:
    LGACVS01:
      return_code: '00'
    LGACDB02:
      return_code: '00'

sql:
  default_identity: 100001

  selects:
    - key: customer-by-policy
      when:
        CA-POLICY-NUM: 'POLICY-0001'
      values:
        DB2-CUSTOMERNUM-INT: 100001
        CA-STATUS: 'ACTIVE'

files:
  CUSTOMER-FILE:
    records:
      - CUSTOMER-NUMBER: 100001
        CUSTOMER-FIRST-NAME: 'Ada'
        CUSTOMER-LAST-NAME: 'Lovelace'
    end_of_file_after: 1

logging:
  display_writes: true
  mask_fields:
    - WS-CS-PASSWORD
    - D2-CUSTSECR-PASS
```

Fixture selection order:

1. Exact operation fixture.
2. Fixture selected by input key or predicate.
3. Named default fixture.
4. Explicit diagnostic.

Random values must not be used as a fallback.

---

# Source rewriting

## Recommended strategy

Use source-preserving span replacement for the first version.

The generator should:

1. Collect all edits before applying them.
2. Validate every source range.
3. Reject ambiguous or overlapping edits.
4. Insert declarations in a stable section.
5. Apply replacements from the end of the file toward the beginning.
6. Preserve comments and untouched formatting.
7. Reparse the generated COBOL.

A replacement should include a trace comment:

```cobol
      * STUBGEN op-0017 rule=cics.get-counter.v1
           ADD 1 TO STUB-CICS-COUNTER
           MOVE STUB-CICS-COUNTER TO LASTCUSTNUM
           MOVE 0 TO WS-RESP
```

Do not regenerate the entire COBOL file unless the AST library has a reliable COBOL writer. Full regeneration may lose comments, compiler directives, fixed-format layout, and vendor-specific syntax.

---

## Declaration planning

Generated variables should use a collision-resistant prefix:

```cobol
       01 STUB-CICS-COUNTER PIC S9(9) COMP VALUE 100000.
       01 STUB-SQLCODE PIC S9(9) COMP VALUE 0.
       01 STUB-SCENARIO PIC X(32) VALUE 'happy-path'.
```

Before adding a declaration, check:

- Existing AST symbols.
- Data-description entries.
- Copybook symbols.
- Linkage-section symbols.
- Generated symbols from earlier rules.

The planner must detect:

- Duplicate names.
- Numeric versus alphanumeric incompatibility.
- `COMP`, `COMP-3`, and display usage.
- Pointer declarations.
- Group-item layouts.
- Fixed-format column restrictions.
- Compiler dialect differences.

Generated variables should be inserted into `WORKING-STORAGE SECTION` unless they specifically belong in linkage or another section.

---

# Optional LLM component

## Recommendation

Do not use an LLM for known operations such as:

- SQL `INSERT`.
- SQL `SELECT`.
- CICS `LINK`.
- CICS `GET COUNTER`.
- File `READ`.
- File `WRITE`.

These should use deterministic rules.

Use an LLM only for:

- Unfamiliar vendor-specific statements.
- Ambiguous operation intent.
- Copybook-to-fixture mapping suggestions.
- Explaining compiler diagnostics.
- Suggesting a rule classification for human review.

The LLM should receive only a small operation context, not the entire source file.

Example structured response:

```json
{
  "classification": "FILE_READ",
  "intent": "load_customer_record",
  "input_symbols": ["CUSTOMER-FILE"],
  "output_symbols": ["CUSTOMER-RECORD"],
  "status_symbol": "CUSTOMER-FILE-STATUS",
  "recommended_rule": "file.read.v1",
  "fixture_key": "customer_record_001",
  "confidence": 0.94,
  "assumptions": [
    "The FD record layout is available"
  ]
}
```

The response must be rejected if it:

- Introduces undeclared variables.
- References symbols outside the supplied AST context.
- Returns free-form replacement COBOL.
- Selects an unsupported rule.
- Has low confidence without approval.
- Contradicts the source's control-flow structure.

The final COBOL must always be emitted by deterministic code.

---

# LangGraph and LangChain decision

## First release

LangGraph and LangChain are not necessary.

A normal CLI pipeline is easier to test:

```text
load
-> analyze AST
-> extract operations
-> classify operations
-> create transformation plan
-> rewrite source
-> reparse
-> compile
-> run scenarios
-> create report
```

Recommended initial dependencies:

- Python.
- Pydantic.
- Typer or `argparse`.
- PyYAML.
- Pytest.
- The existing Java AST generator.

The Java AST generator can initially be invoked as a subprocess.

## Later agentic version

LangGraph becomes useful if the system needs:

1. Parser execution.
2. Unknown-operation analysis.
3. LLM classification.
4. Transformation generation.
5. Compiler execution.
6. Diagnostic repair.
7. Human approval.
8. Scenario execution.
9. Artifact publication.

LangGraph should orchestrate these stages. It should not replace the deterministic rule engine or source rewriter.

LangChain may help with:

- Structured LLM output.
- Prompt templates.
- Model adapters.
- Tool calling.

Neither library solves COBOL parsing, source-span mapping, compiler compatibility, or semantic correctness.

---

# CLI design

Example commands:

```text
stubgen analyze ^
  --source C:\path\LGACDB01.cbl ^
  --ast C:\path\out.json ^
  --copybook-dir C:\path\copybooks ^
  --dialect ibm-enterprise
```

```text
stubgen generate ^
  --source C:\path\LGACDB01.cbl ^
  --ast C:\path\out.json ^
  --policy policies\local-default.yaml ^
  --fixtures fixtures\LGACDB01.yaml ^
  --out out\LGACDB01
```

```text
stubgen validate ^
  --artifact out\LGACDB01 ^
  --compiler gnucobol
```

```text
stubgen run ^
  --artifact out\LGACDB01 ^
  --scenario happy-path
```

The `analyze` command should not modify source files. It should show the detected resource operations and proposed rules before generation.

---

# Suggested project layout

```text
_stub_generator/
  README.md
  pyproject.toml

  src/
    stubgen/
      cli.py
      ast_adapter.py
      source_spans.py
      symbols.py
      ir.py
      extractor.py
      planner.py
      fixtures.py
      declarations.py
      rewriter.py
      validator.py
      reporting.py

      rules/
        base.py
        sql.py
        cics.py
        file_io.py
        call.py

  policies/
    local-default.yaml

  fixtures/
    LGACDB01.yaml

  tests/
    test_ast_adapter.py
    test_source_spans.py
    test_sql_rules.py
    test_cics_rules.py
    test_file_rules.py
    test_golden_generation.py
    golden/
```

---

# End-to-end algorithm

## Phase 1: load

1. Validate source and AST paths.
2. Parse AST JSON.
3. Record parser version.
4. Load source and encoding configuration.
5. Load copybooks.
6. Build a symbol index.
7. Load policy and fixtures.

## Phase 2: discover

1. Traverse all AST children.
2. Identify `ExecEndExec` nodes.
3. Determine whether each block is SQL or CICS.
4. Extract the embedded statement.
5. Identify file and CALL nodes from typed AST nodes.
6. Resolve exact source spans.
7. Identify input/output symbols.
8. Identify status variables.
9. Record enclosing paragraphs and conditions.

## Phase 3: plan

1. Match each operation to a deterministic rule.
2. Select fixture values.
3. Plan generated declarations.
4. Plan compatibility macro replacements.
5. Ask the optional LLM only about unresolved operations.
6. Validate the structured plan.
7. Require approval for partial transformations.

## Phase 4: emit

1. Generate replacement COBOL.
2. Add trace comments.
3. Insert declarations.
4. Verify edit hashes.
5. Reject overlapping edits.
6. Apply edits in reverse source-offset order.
7. Write generated COBOL.
8. Write the manifest.

## Phase 5: validate

1. Reparse generated COBOL.
2. Check that unsupported external statements are gone or explicitly approved.
3. Compile with the selected compiler.
4. Run happy-path scenarios.
5. Run error-path scenarios.
6. Run EOF and repeated-read scenarios.
7. Capture output.
8. Write the final report.

---

# Handling LGACDB01

The supplied program is a good integration test because it contains:

- `EXEC SQL INCLUDE SQLCA`.
- `EXEC SQL INCLUDE LGCMAREA`.
- CICS runtime fields.
- CICS `ABEND`.
- CICS `RETURN`.
- CICS `LINK`.
- CICS `GET COUNTER`.
- CICS `ASKTIME`.
- CICS `FORMATTIME`.
- SQL `INSERT`.
- SQL identity retrieval.
- Error handling based on `SQLCODE` and CICS responses.

A first transformation plan is:

1. Replace SQLCA inclusion with a local SQLCA compatibility declaration.
2. Resolve `LGCMAREA` from the copybook directory.
3. If `LGCMAREA` is unavailable, require an explicit local commarea schema.
4. Add local definitions for referenced EIB fields.
5. Replace `GET COUNTER` with a deterministic counter fixture.
6. Set `WS-RESP` to the configured normal response.
7. Replace SQL inserts with displays of the input fields.
8. Set `SQLCODE` to zero for successful SQL stubs.
9. Replace `IDENTITY_VAL_LOCAL()` with a deterministic customer number.
10. Replace CICS links with displays and configured return codes.
11. Replace time operations with a deterministic clock fixture.
12. Replace CICS returns and abends according to policy.
13. Reparse and compile the generated program.
14. Run success and failure scenarios.

The generator must report unresolved copybooks and runtime symbols separately. Removing `EXEC` blocks alone does not guarantee that the program will compile.

---

# Validation requirements

Generation succeeds only if:

- Every discovered operation is transformed or explicitly approved.
- Every replacement span matches the original source hash.
- The generated program reparses.
- Generated symbols are declared.
- Generated symbols have compatible PIC/USAGE definitions.
- The generated file compiles under the selected compiler profile.
- The manifest matches the generated source.
- Scenario execution produces expected status and data-flow results.

---

# Testing strategy

## Unit tests

Test:

- Recursive AST traversal.
- SQL/CICS node identification.
- Source-span resolution.
- Repeated source text.
- Fixed-format COBOL columns.
- SQL host-variable extraction.
- CICS operand extraction.
- Fixture selection.
- EOF behavior.
- Numeric literal generation.
- Macro replacement.
- Declaration collision detection.
- Edit overlap detection.
- Secret masking.

## Golden tests

Maintain expected output for small programs containing:

- One SQL read.
- One SQL write.
- One CICS link.
- One CICS counter.
- One file read.
- One file write.
- Nested `IF`.
- Error branches.
- Multiple identical operations.

The LGACDB01 example should become a golden integration fixture after its copybooks or local schemas are available.

## Runtime scenarios

At minimum:

- Happy path.
- SQL failure.
- CICS link failure.
- File EOF.
- Indexed-file invalid key.
- Multiple counter reads.
- Missing fixture.
- CICS ABEND path.

Assertions should check data flow, not only process exit code.

Examples:

```text
A SQL read populated the expected host variable.
A file read took the AT END branch after fixture exhaustion.
A CICS LINK emitted the configured program and commarea.
A SQL INSERT displayed the expected non-secret values.
An error response caused the original error branch to execute.
```

---

# Example policy

```yaml
dialect: ibm-enterprise

unknown_operation: fail
allow_partial: false

return_behavior:
  cics_return: goback
  cics_abend: goback
  continue_after_abend: false

fixtures:
  missing_value: fail

logging:
  enabled: true
  display_writes: true
  mask_fields:
    - '*PASSWORD*'
    - '*SECRET*'
    - '*TOKEN*'

llm:
  enabled: false
  max_confidence_required: 0.90
  require_approval_below: 0.98
```

---

# Security considerations

COBOL programs may contain credentials, customer data, account numbers, or secrets.

The system should:

- Mask fields containing `PASSWORD`, `SECRET`, `TOKEN`, `KEY`, or `CREDENTIAL`.
- Avoid sending full source files to an external LLM.
- Send only the smallest AST operation context required.
- Support a local-only mode.
- Never display secrets unless explicitly permitted.
- Keep the original source immutable.
- Record rule versions, fixture versions, model versions, and policy versions.
- Store generated artifacts separately from production source.

---

# Risks and mitigations

| Risk | Mitigation |
|---|---|
| AST parser changes node names | Parser-version adapter and golden tests |
| AST positions do not map directly to source | Exact span verification and source hashes |
| Generated code changes control flow | Replace only leaf operation spans and test branches |
| Missing copybook layout | Require copybook or explicit schema |
| Random fixture values | Use named deterministic fixtures |
| Compiler dialect mismatch | Explicit compiler profile and compile gate |
| LLM hallucination | Structured JSON only, symbol validation, no direct code emission |
| Secrets printed to terminal | Field masking and output allowlists |
| Nested or overlapping spans | Interval validation and leaf-node selection |
| Status checks become invalid | Rule contracts must set existing status variables |
| CICS RETURN behavior changes | Configurable policy and runtime scenarios |

---

# Roadmap

## Milestone 1: AST inspection

- Implement AST adapter.
- Traverse nested children.
- Extract SQL/CICS nodes.
- Resolve exact source spans.
- Produce an analysis manifest.
- Add golden tests.

## Milestone 2: deterministic SQL/CICS rewriting

- Add declaration planner.
- Implement SQL include, insert, and identity rules.
- Implement CICS counter, link, return, abend, and time rules.
- Add local SQL and CICS compatibility declarations.
- Reparse generated output.

## Milestone 3: compiler validation

- Add compiler profiles.
- Compile generated programs.
- Classify compiler errors.
- Add scenario execution.
- Capture `DISPLAY` output.

## Milestone 4: file and CALL support

- Extract FD layouts.
- Implement stateful read fixtures.
- Implement EOF and invalid-key behavior.
- Implement write/rewrite/delete logging.
- Add configured CALL contracts.

## Milestone 5: optional agentic workflow

- Add LLM classification for unknown constructs.
- Add structured plan validation.
- Add human approval for low-confidence changes.
- Add compiler-diagnostic repair loops.
- Introduce LangGraph only if durable multi-step orchestration is required.

---

# Definition of done

The first usable version should be able to:

1. Load COBOL source and AST JSON.
2. List every external operation with an exact source span.
3. Explain the planned replacement before generation.
4. Generate a new COBOL file without modifying the original.
5. Preserve surrounding control flow.
6. Populate read destinations with deterministic fixture values.
7. Display meaningful write and call information.
8. Preserve status and error-path behavior.
9. Mask sensitive values.
10. Reparse the generated source.
11. Compile it using a configured local compiler.
12. Run happy-path and error-path scenarios.
13. Produce a manifest and human-readable report.

The system should be agentic in how it investigates unknown constructs and coordinates validation, but the generated COBOL should come from deterministic rules, typed plans, explicit fixtures, and compiler validation.