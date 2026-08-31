# 4. Program Analysis

Modules: `analysis/symbol_table.py`, `analysis/pic_parser.py`,
`analysis/exec_text_parser.py`

These three supply the *semantic context* a mock needs: what fields exist and
what shape they are, and what the command it is replacing was actually asking
for.

## 4.1 `symbol_table.py` — the DATA DIVISION

### Why it is built from text, not the AST

The AST *does* expose data items (`DataDescriptionEntry1/2/4` with
`LevelNumber`, `PictureClause`, `RedefinesClause` children). Text scanning is
used anyway, for two reasons:

1. The same table is needed on the **fallback path**, where no AST exists. One
   implementation means one set of behaviours to reason about and test.
2. Data-description entries are **strictly regular** in fixed format, so a text
   scan is both simple and exact — far cheaper than walking 4–5 tree levels per
   attribute.

The lexer mask keeps comment lines and literals out of the scan, so this is not
naive regexing over raw source.

### The scan

Walks lines from `DATA DIVISION` to `PROCEDURE DIVISION`, tracking the current
section (`WORKING-STORAGE`, `LINKAGE`, `LOCAL-STORAGE`, `FILE`).

Entries are accumulated until their terminating period, because a single entry
frequently spans lines:

```cobol
       01  WS-POLICY-RECORD
                        PIC X(64)
                        VALUE SPACES.
```

```python
pending += (" " if pending else "") + code.strip()
if "." not in pending:
    continue                      # entry continues on the next line
while "." in pending:             # one line may hold several entries
    head, pending = pending.split(".", 1)
    _consume_entry(head, section, stack, table, pending_offset)
```

### Hierarchy reconstruction

Level numbers imply the tree. A stack of `(level, name)` is popped until the top
is a lower level than the current entry:

```python
while stack and stack[-1][0] >= level:
    stack.pop()
parent = stack[-1][1] if stack else None
...
if pic_m is None:                 # a group item can own children
    stack.append((level, name))
```

Only entries **without** a `PICTURE` are pushed, since only groups have children.
Level 88 condition names are skipped entirely — they carry no storage.

### `elementary_fields()` — and the REDEFINES rule

This drives record population for `READ ... INTO(...)`. It walks a group and
returns its PIC-bearing leaves:

```python
for child_name in sym.children:
    child = self.get(child_name)
    if child is None or child.is_condition or child.redefines:
        continue                                    # <-- the important line
    out.extend(self.elementary_fields(child_name, _depth + 1))
```

**`REDEFINES` children are skipped.** A redefinition is an alternate view of the
*same bytes*; populating both would write the same storage twice through two
different interpretations, and the second would silently corrupt the first. Only
the first interpretation is filled. `LGCMAREA` has 3-way and 5-way nested
`REDEFINES`, so this is exercised heavily.

`_depth > 20` guards against a malformed hierarchy recursing forever.

### What is recorded

```python
@dataclass
class Symbol:
    name, level, section
    pic_text, usage, redefines, occurs, value
    parent, children, offset
```

with derived properties `pic` (parsed), `is_group`, `is_filler`, `is_pointer`,
`is_condition`. `FILLER` contributes storage but is never registered by name,
since it cannot be referenced.

**Result on `lgucvs01`:** 106 symbols / 113 entries, correctly separating
`WS-RESP` (WORKING-STORAGE) from `CA-CUSTOMER-NUM` (LINKAGE), and resolving
`DFHCOMMAREA` as a group with 7 children.

## 4.2 `pic_parser.py` — PICTURE clauses

Only what the mock generator actually needs, so a generated literal always fits
its receiving field.

```python
_TOKEN = re.compile(r"([9AXZSVP*$,./+-])(?:\((\d+)\))?", re.IGNORECASE)
```

Preprocessing strips the `PIC`/`PICTURE IS` keyword and everything from a usage
clause onward, so `S9(4)V99 COMP` and `X(20) VALUE SPACES` both reduce to their
picture string.

Symbol handling:

| Symbol | Effect |
|---|---|
| `S` | `signed = True` |
| `V` | implied decimal point; subsequent `9`s count as decimals |
| `9` | digit (integer or decimal depending on `V`) |
| `X` | alphanumeric position |
| `A` | alphabetic position |
| `Z * $ , . + -` | marks the picture *edited*; `Z`/`*` also count digits |

Category precedence: any `X` → `ALPHANUMERIC`; else any `A` → `ALPHABETIC`; else
digits → `NUMERIC` or `NUMERIC_EDITED`; else `UNKNOWN`.

```
X(20)        -> ALPHANUMERIC, length 20
S9(4)V99 COMP-> NUMERIC, digits 4, decimals 2, signed
9(10)        -> NUMERIC, digits 10
```

`UNKNOWN` is meaningful, not a failure: `dummy_values` returns `None` for it, so
the field is left alone rather than given a fabricated value.

## 4.3 EXEC option parsing

`exec_text_parser.py` recovers structure from the raw text the AST hands over
unparsed. The grammar is small and regular: a verb, then options that are either
bare keywords (`UPDATE`, `NODUMP`) or `KEYWORD(argument)`.

### Two-word verbs — the subtle case

CICS has verbs whose second word is part of the verb identity:
`SEND MAP`, `WRITEQ TS`, `GET COUNTER`, `HANDLE CONDITION`, …

But some of those qualifiers **also carry an argument**:

```cobol
EXEC CICS GET COUNTER(GENAcount) POOL(GENApool) VALUE(WS-V) END-EXEC
```

Here `GET COUNTER` is the verb *and* `COUNTER(GENAcount)` is an option of it. The
rule:

```python
if (first, second) in _TWO_WORD_VERBS:
    verb = f"{first} {second}"
    after = second_at + len(second)
    # A qualifier carrying its own argument is ALSO an option, so leave it
    # in the option stream.  A bare qualifier (WRITEQ TS) is consumed here.
    if not (after < len(text) and text[after:].lstrip()[:1] == "("):
        consumed_chars = after
```

Getting this wrong caused **166 of 537 EXEC blocks to fail parsing** — the
parser consumed `COUNTER`, then met `(GENAcount)` with no keyword and gave up.
After the fix: **537 / 537 parse cleanly, zero failures.**

### Parenthesis matching

`_match_paren()` scans for the closing paren while skipping quoted literals, so
`ABCODE('A(B')` parses correctly rather than terminating at the paren inside the
string.

### Verb coverage produced

```
LINK 95   RETURN 84   SEND MAP 43   DELETE COUNTER 37   DEFINE COUNTER 37
QUERY COUNTER 36   ABEND 24   ASKTIME 22   FORMATTIME 22   WRITEQ TS 17
SYNCPOINT 10   INSERT 9   ASSIGN 9   SEND TEXT 9   RECEIVE MAP 9
SELECT 8   READQ TS 7   DELETEQ TS 6   HANDLE AID 5   HANDLE CONDITION 5
UPDATE 5   RECEIVE 4   READ 4   OPEN 3   CLOSE 3   FETCH 3 ... 38 verbs total
```

### SQL extraction

Deliberately narrow — no attempt at a real SQL grammar. Just enough to mock:

| Extracted | How |
|---|---|
| verb | first token; `DECLARE ... CURSOR` and `DECLARE ... TABLE` are distinct forms |
| `_HOSTVARS` | every `:NAME` in order, de-duplicated |
| `_INTO` | host variables of the `INTO` clause, stopping at `FROM`/`WHERE`/`VALUES`/`SET`/… |
| `_TABLE` | per-verb pattern: `FROM x`, `INTO x`, `UPDATE x` |
| `CURSOR` | cursor name for `DECLARE`/`OPEN`/`FETCH`/`CLOSE` |

The `DECLARE` form needs care because attributes vary between the name and the
`CURSOR` keyword:

```cobol
EXEC SQL DECLARE Cust_Cursor Insensitive Scroll Cursor For SELECT ...
EXEC SQL DECLARE POLICY_CURSOR CURSOR WITH HOLD FOR SELECT ...
```

So `CURSOR` is *looked for* in the first few tokens rather than assumed to be
token 2:

```python
head = [t.upper() for t in tokens[1:6]]
if "CURSOR" in head:   verb = "DECLARE CURSOR"
elif "TABLE" in head:  verb = "DECLARE TABLE"
```

### Argument helpers

Two small functions that keep the rules honest about what they are looking at:

```python
split_arg_identifier("WS-REC")      -> "WS-REC"     # a plain reference
split_arg_identifier("'KSDSCUST'")  -> None         # a literal, not a field
split_arg_identifier("WS-A + 1")    -> None         # an expression

literal_of("'KSDSCUST'")            -> "KSDSCUST"
literal_of("WS-REC")                -> None
```

Returning `None` rather than guessing is what stops a rule emitting
`MOVE ... TO 'KSDSCUST'`.

### When parsing fails

`ExecCommand.parse_ok` goes `False` on unexpected punctuation or an unbalanced
paren. The pipeline then routes to the generic fallback rule rather than letting
a verb-specific rule act on half-understood options — the fallback's
trace-plus-success-status behaviour is safe to emit with zero semantic
understanding of the command.
