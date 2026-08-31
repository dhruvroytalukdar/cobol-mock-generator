# 9. CLI & Operations

Modules: `cli.py`, `gnucobol/gnucobol_runner.py`, `build_selection.py`

## 9.1 Subcommands

Each subcommand stops the pipeline at a stage boundary, so a run can be
inspected at any point.

```bash
python -m cobol_transformer.cli <subcommand> SOURCE.cbl [options]
```

| Subcommand | Stages | Writes | Exit code |
|---|---|---|---|
| `inline` | 1 | expanded `.cbl` | 0 |
| `detect` | 1–4 | nothing (prints a table) | 0 |
| `transform` | 1–7 | `.cbl` + manifest + report | 1 if any construct was skipped |
| `build` | 1–8 | the above + compiled binary | 2 if compilation failed |
| `verify` | 1–7 + proof | nothing | 3 if an undeclared difference was found |

### `detect` — the dry run

Shows what would be mocked without writing anything. The fastest way to
understand a program:

```
  LINE  CAT    VERB             RULE                   PERIOD STATUS
-----------------------------------------------------------------------
   359  cics   ABEND            cics_abend             False  commented_and_mocked
   406  sql    SELECT           sql_select             True   commented_and_mocked
   462  cics   LINK             cics_link              True   commented_and_mocked
-----------------------------------------------------------------------
backend=ast  constructs=10  fallback=0  skipped=0
```

The `PERIOD` column exposes terminator handling; `backend` says whether the AST
or the lexical fallback was used.

### `build --run`

```bash
python -m cobol_transformer.cli build genapp-files/src/lgicdb01.cbl \
    -o out.cbl --run
```

```
transformed -> out.cbl
compile: OK (exit 0)
run: exit 0
>>> MOCK SELECT @GET-CUSTOMER-INFO: TABLE=CUSTOMER
>>> MOCK RETURN @MAINLINE-END
```

Compiler errors are written to stderr **verbatim** — never summarised or
swallowed — and the manifest/report are still written so a failure is
diagnosable.

### `verify` — the equivalence proof

```bash
$ python -m cobol_transformer.cli verify genapp-files/src/lgicdb01.cbl
lgicdb01.cbl: VERIFIED - 483 lines reconstruct exactly; 10 mocked constructs
```

A failure prints each unexpected difference with both sides, and exits 3.

## 9.2 Common flags

| Flag | Default | Effect |
|---|---|---|
| `--copybooks DIR` | — | search directory, repeatable; the source's own directory is always appended |
| `--no-ast` | off | skip the AST backend entirely and use the lexical detector |
| `--ast-url URL` | `http://127.0.0.1:4010` | AST server location |
| `--rows-per-cursor N` | 1 | rows a mocked cursor or browse returns before reporting end-of-data |
| `--seed N` | 1 | seed for dummy-value selection |
| `--continue-on-missing-copybook` | on | placeholder + warning instead of a hard error |
| `--quiet` | off | suppress progress output |

`--rows-per-cursor` is the one worth knowing: it controls how many iterations a
`PERFORM UNTIL SQLCODE = 100` loop makes. Raising it exercises more of a
program's row-handling logic.

## 9.3 The GnuCOBOL runner

```python
args = [self.cobc, "-x", "-std=default", "-Wno-unfinished"]
```

- **`-x`** builds an executable (rather than `-m`, a loadable module)
- **`-std=default`** — GnuCOBOL's own dialect, which accepts the fixed-format
  IBM-flavoured source in this corpus
- **`-free` is deliberately NOT passed.** This corpus is fixed-format,
  80-column source; free format would misread every line

### WSL path translation

On Windows `cobc` lives inside WSL, so commands are routed through it and paths
are translated:

```python
def to_wsl_path(path):
    p = os.path.abspath(path).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        return f"/mnt/{m.group(1).lower()}/{m.group(2)}"     # C:\a\b -> /mnt/c/a/b
    return p
```

WSL is auto-detected — used when the platform is Windows and `cobc` is not on
the native PATH.

### Run timeouts are treated as failures

```python
except subprocess.TimeoutExpired as exc:
    return CompileResult(False, -1, ..., f"program timed out after {timeout}s "
                                          "(possible infinite loop)")
```

This is how the `lgicvs01` infinite loop was caught rather than hanging the
build — a timeout is reported as a failed run with a specific hint, not silently
retried.

## 9.4 Running the AST server

```bash
cobol-ast-server.bat --port 4010          # Windows
./cobol-ast-server.sh --port 4010         # macOS / Linux
curl http://127.0.0.1:4010/health
# {"ok": true, "service": "cobol-ast-server", "lsp": "running"}
```

Requires **Java 21** and the IBM Z Open Editor extension at
`~/.vscode/extensions/ibm.zopeneditor-*`. Boot takes a few seconds; keep it
running across a batch, which is the whole reason the HTTP surface is preferred
over the one-shot CLI.

Without the server the pipeline still works — it falls back to the lexical
detector and records `W-AST-UNAVAILABLE` in the manifest.

## 9.5 `build_selection.py`

Reproduces the ten delivered programs:

```bash
python build_selection.py
```

```
PROGRAM       LOC   OUT BACKEND       MOCK  FB SKIP  VERIFY   COMPILE  RUN
--------------------------------------------------------------------------
lgipdb01     1030  1452 ast             25   0    0  OK       OK       ok
lgwebst5      802   957 ast             51   0    0  OK       OK       ok
lgapdb01      595   896 ast             28   0    0  OK       OK       ok
lgupdb01      535   834 ast             23   0    0  OK       OK       ok
lgacdb01      328   606 ast             17   0    0  OK       OK       ok
lgtestp4      318  1137 ast             20   0    0  OK       OK       ok
lgtestp1      318  1170 ast             26   0    0  OK       OK       ok
lgtestp2      300  1138 ast             25   0    0  OK       OK       ok
lgtestp3      299  1131 ast             25   0    0  OK       OK       ok
lgicdb01      245   518 ast             10   0    0  OK       OK       ok
--------------------------------------------------------------------------
10/10 programs verified, compiled and ran cleanly
```

### Selection rationale

Scope is the **26 programs the AST backend can parse**. Five are excluded
because the language server refuses to emit an AST for them:

```python
AST_EXCLUDED = ["lgicvs01", "lgipvs01", "lgsetup", "lgstsq", "lgtestc1"]
```

Within that scope: the five largest by line count, then the next five. Note that
once the excluded programs are removed **the corpus has nothing between 328 and
535 lines**, so the second group is the closest available tier rather than a
literal ~500 lines.

The script **treats a fallback as a failure**:

```python
used_ast = res.manifest.detection_backend == "ast"
if not (v.ok and comp.ok and runstat == "ok" and used_ast):
    failures += 1
```

Otherwise a silent fallback could leave the AST path untested while the run
still reported success.

### Artefacts per program

```
transformed/lgicdb01.cbl             the transformed program
transformed/lgicdb01.manifest.json   machine-readable record
transformed/lgicdb01.report.txt      human-readable summary
transformed/lgicdb01.stdout.txt      captured output of the compiled run
transformed/lgicdb01                 the compiled binary
```

## 9.6 Running the tests

```bash
python -m pytest tests/unit -q
# 198 passed, 5 skipped
```

Skips are the AST-parity test on the five excluded programs. To run without any
Java at all, the end-to-end tests already use `use_ast=False`, so the core
equivalence guarantee is checkable with only Python and the corpus.

## 9.7 Requirements

| Component | Needed for |
|---|---|
| Python 3.9+ | everything |
| GnuCOBOL 3.x (`cobc`) | `build`, compile tests |
| WSL | running `cobc` on Windows |
| Java 21 + Z Open Editor | the AST backend (optional — fallback exists) |
| pytest | the test suite |

Verified on Python 3.12, GnuCOBOL 3.1.2, Z Open Editor 6.7.0.
