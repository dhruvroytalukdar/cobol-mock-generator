# Cobol AST Generator Command Line Tools

A standalone Java CLI (and optional HTTP server) that generates COBOL AST JSON by spawning the IBM Z Open Editor language-server JARs and driving them over LSP JSON-RPC (stdio) — no VS Code, no OSGi embedding.


## Prerequisites

| Requirement | Notes |
|---|---|
| **Java 21 JRE** | Required at runtime by the Z Open Editor OSGi bundles (e.g. IBM Semeru 21 JRE or Eclipse Temurin 21) |
| **Java 21 JDK** | Required only to **build** (e.g. Eclipse Temurin 21 JDK) |
| **Maven 3.6+** | To build |
| **IBM Z Open Editor** | Extension installed at `~/.vscode/extensions/ibm.zopeneditor-X.Y.Z` (Windows: `%USERPROFILE%\.vscode\extensions`) |

## Run — CLI (one-shot)

### macOS / Linux — use the shell script

```bash
./cobol-ast-cli.sh path/to/MYPROG.cbl
./cobol-ast-cli.sh --copybooks path/to/cpy --output /tmp/out.json path/to/MYPROG.cbl
```

### Windows — use the batch file

```bat
cobol-ast-cli.bat path\to\MYPROG.cbl
cobol-ast-cli.bat --copybooks path\to\cpy --output C:\tmp\out.json path\to\MYPROG.cbl
```

### Direct `java` invocation

```bash
LSP=~/.vscode/extensions/ibm.zopeneditor-6.6.1/language-server

# macOS / Linux  (classpath separator: colon)
java -cp "target/cobol-ast-generator.jar:$LSP/plugins/*" \
     com.ibm.zta.cobolast.CobolAstCli \
     --lsp-root "$LSP" \
     --java /path/to/java21/bin/java \
     path/to/MYPROG.cbl
```

```bat
rem Windows  (classpath separator: semicolon)
java -cp "target\cobol-ast-generator.jar;%LSP%\plugins\*" ^
     com.ibm.zta.cobolast.CobolAstCli ^
     --lsp-root "%LSP%" ^
     --java C:\path\to\java21\bin\java.exe ^
     path\to\MYPROG.cbl
```

Output is written to `MYPROG-ast.json` next to the source file.

## CLI options

```
  --lsp-root <path>      IBM Z Open Editor language-server directory
                         (auto-detected from ~/.vscode/extensions)
  --java <path>          Java 21 executable (default: java)
  --output <path>        Output file (default: <basename>-ast.json)
  --copybooks <dir>      Copybook directory (repeatable)
  --version 1|2          AST serializer version (default: 1)
                           1 → cobol.ast.serialize
                           2 → v2.cobol.ast.serialize
  --max-heap <mb>        Language server JVM max heap MB (default: 1536)
  --timeout <sec>        Seconds to wait for AST (default: 120)
  --verbose              Print LSP traffic to stderr
  --quiet / -q           Suppress all stderr output; print output path to stdout
```

---

## Run — HTTP server

The HTTP server starts a single long-lived LSP process at startup and reuses it
for all requests — no per-request Equinox boot overhead.

### macOS / Linux — use the shell script

```bash
./cobol-ast-server.sh
./cobol-ast-server.sh --port 4010 --host 0.0.0.0 --api-token secret
```

### Windows — use the batch file

```bat
cobol-ast-server.bat
cobol-ast-server.bat --port 4010 --host 0.0.0.0 --api-token secret
```

### Direct `java` invocation

```bash
LSP=~/.vscode/extensions/ibm.zopeneditor-6.6.1/language-server

# macOS / Linux
java -cp "target/cobol-ast-generator.jar:$LSP/plugins/*" \
     com.ibm.zta.cobolast.CobolAstHttpServer \
     --lsp-root "$LSP" \
     --java /path/to/java21/bin/java \
     --port 4010
```

```bat
rem Windows
java -cp "target\cobol-ast-generator.jar;%LSP%\plugins\*" ^
     com.ibm.zta.cobolast.CobolAstHttpServer ^
     --lsp-root "%LSP%" ^
     --java C:\path\to\java21\bin\java.exe ^
     --port 4010
```

### HTTP server options

```
  --host <address>     Bind address (default: 127.0.0.1)
  --port <n>           Port (default: 4010)
  --lsp-root <path>    IBM Z Open Editor language-server directory
  --java <path>        Java 21 executable (default: java)
  --version 1|2        AST serializer version (default: 1)
  --max-heap <mb>      Language server JVM max heap MB (default: 1536)
  --timeout <sec>      Seconds to wait for AST per request (default: 120)
  --api-token <token>  Bearer token required in Authorization header
  --verbose            Print LSP traffic to stderr
```

### Endpoints

#### `GET /health`

```bash
curl http://127.0.0.1:4010/health
```

```json
{ "ok": true, "service": "cobol-ast-server", "lsp": "running" }
```

#### `POST /generate-ast` — single COBOL file

Send the raw COBOL source as the request body. Use the optional `X-Filename` header
to supply the filename (defaults to `source.cbl`).

```bash
curl -X POST http://127.0.0.1:4010/generate-ast \
     -H 'Content-Type: text/plain' \
     -H 'X-Filename: MYPROG.cbl' \
     --data-binary @path/to/MYPROG.cbl
```
Do not forget to add '@' before the Cobol file name.

#### `POST /generate-ast` — ZIP archive (COBOL + copybooks)

Pack the COBOL source and any copybooks into a ZIP file and send it.
The server extracts the archive to a temp directory and uses all
extracted directories for copybook resolution. The first `.cbl`/`.cob`
file found (alphabetical order) is treated as the main source.

```bash
zip upload.zip MYPROG.cbl copybooks/*.cpy
curl -X POST http://127.0.0.1:4010/generate-ast \
     -H 'Content-Type: application/zip' \
     --data-binary @upload.zip
```
Do not forget to add '@' before the zip file name.

#### Response

```json
{
  "ok": true,
  "filePath": "MYPROG.cbl",
  "ast": { ... }
}
```

Error response:

```json
{ "ok": false, "error": "..." }
```

#### Bearer token authentication

```bash
curl -X POST http://127.0.0.1:4010/generate-ast \
     -H 'Authorization: Bearer YOUR_TOKEN' \
     -H 'Content-Type: application/zip' \
     --data-binary @upload.zip
```

## Copybook resolution

When no `--copybooks` flag is given the tool searches (in order):

1. The source file's own directory
2. `<sourceDir>/cpy`, `<sourceDir>/CPY`
3. `<sourceDir>/copybooks`, `<sourceDir>/COPYBOOKS`, `<sourceDir>/Copybooks`
4. `<sourceDir>/../cpy`, `<sourceDir>/../CPY`
5. `<sourceDir>/../copybooks`, `<sourceDir>/../COPYBOOKS`, `<sourceDir>/../Copybooks`

Extensions tried per directory: `.cpy`, `.CPY`, and no extension (bare name).

When `--copybooks` is supplied the auto-search is skipped and only the given directories (plus the source directory) are used.

## Class-path note

The JAR is intentionally thin (~30 KB). It is compiled against the lsp4j and IBM protocol JARs that live inside the Z Open Editor extension. At runtime those JARs must be on the classpath via `-cp "cobol-ast-generator.jar:$LSP/plugins/*"` (macOS/Linux) or `-cp "cobol-ast-generator.jar;%LSP%\plugins\*"` (Windows). This avoids bundling IBM-licensed code and keeps the artifact small.
