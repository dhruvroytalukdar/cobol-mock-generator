#!/usr/bin/env python3
"""Transform, verify, compile and run the ten selected aws-carddemo programs.

Every program here must use the ``ast`` backend; falling back to the lexical
detector would mean the run silently left the AST path untested, so it is
treated as a failure and the whole run exits non-zero.

Outputs land in ``transformed/aws/``: the ``.cbl`` itself, a JSON manifest, a
human-readable report, and the captured stdout of the compiled program.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
from cobol_transformer.output.writer import write_outputs
from cobol_transformer.pipeline import PipelineOptions, run
from cobol_transformer.verify import verify

REPO = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(REPO, "aws-carddemo-files", "cbl")
COPYBOOK_DIRS = [
    os.path.join(REPO, "aws-carddemo-files", "cpy"),
    os.path.join(REPO, "aws-carddemo-files", "cpy-bms"),
]
OUT = os.path.join(REPO, "transformed", "aws")

SELECTION = [
    "COACTVWC",
    "COBIL00C",
    "COCRDLIC",
    "COCRDSLC",
    "COCRDUPC",
    "CORPT00C",
    "COTRN00C",
    "COTRN02C",
    "COUSR00C",
    "COTRTLIC",
]
#: Excluded: its "cobol.ast.serialize" LSP request never completes -- confirmed
#: via isolated testing to consume enough memory (even at an 8GB JVM heap
#: ceiling, on a fresh LSP session) to trigger a host-level low-memory kill
#: before returning. Not a timeout/heap-size tuning problem; a real
#: scalability limit of the language server against this file's size (4236
#: source lines). Replaced in this selection by COTRTLIC (~2000 lines, from
#: the DB2 transaction-type module of the fuller carddemo repo).
AST_HOSTILE = ["COACTUPC"]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    runner = GnuCobolRunner()
    opts = PipelineOptions(copybook_dirs=COPYBOOK_DIRS)
    failures = 0

    header = (
        f"{'PROGRAM':<11} {'LOC':>5} {'OUT':>5} {'BACKEND':<13} {'MOCK':>4} "
        f"{'FB':>3} {'SKIP':>4}  {'VERIFY':<8} {'COMPILE':<8} RUN"
    )
    print(header)
    print("-" * len(header))

    for name in SELECTION:
        src = os.path.join(SRC, name + ".cbl")
        res = run(src, opts)
        out_cbl = os.path.join(OUT, name + ".cbl")
        write_outputs(
            res,
            output=out_cbl,
            manifest_path=os.path.join(OUT, name + ".manifest.json"),
            report_path=os.path.join(OUT, name + ".report.txt"),
        )

        v = verify(res.expanded_text, res.output_text, res.manifest)
        # Pre-existing mainframe-source quirks (present in the original
        # aws-carddemo .cbl, not introduced by the transform) that GnuCOBOL's
        # default strictness rejects: a REDEFINES item larger than the item
        # it redefines (CORPT00C's JOB-DATA-2); a data item whose level
        # number doesn't monotonically descend within its group (COCRDLIC's
        # WS-SCREEN-DATA at level 05 after sibling level-10 items); and a
        # REDEFINES referring to an item other than the one immediately
        # preceding it (COTRTLIC's chained FILLER REDEFINES CTRTLIAI /
        # REDEFINES CTRTLIAO pair copied straight from its BMS map).
        comp = runner.compile(
            out_cbl, os.path.join(OUT, name),
            extra_flags=[
                "-flarger-redefines-ok",
                "-frelax-level-hierarchy",
                "-findirect-redefines",
            ],
        )
        runstat = "-"
        if comp.ok:
            r = runner.run(os.path.join(OUT, name), timeout=30)
            runstat = "ok" if r.ok else f"exit{r.returncode}"
            with open(os.path.join(OUT, name + ".stdout.txt"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write(r.stdout)
            if not r.ok:
                fh_err = r.stderr.strip().splitlines()[-1:] or [""]
                print("    run stderr:", fh_err[0][:70])
        else:
            print("    compile errors:")
            for line in (comp.stderr or "").splitlines()[:6]:
                print("      " + line[:100])

        with open(src) as fh:
            loc = sum(1 for _ in fh)
        s = res.manifest.to_dict()["summary"]
        used_ast = res.manifest.detection_backend == "ast"
        if not used_ast:
            print(f"    ERROR: expected the AST backend, got "
                  f"{res.manifest.detection_backend}: {res.manifest.ast_error}")
        print(
            f"{name:<11} {loc:>5} {len(res.output_text.splitlines()):>5} "
            f"{res.manifest.detection_backend:<13} {s['constructs']:>4} "
            f"{s['fallback_rules_used']:>3} {s['skipped']:>4}  "
            f"{('OK' if v.ok else 'DIFF'):<8} "
            f"{('OK' if comp.ok else 'FAIL'):<8} {runstat}"
        )
        if not (v.ok and comp.ok and runstat == "ok" and used_ast):
            failures += 1

    print("-" * len(header))
    print(f"{len(SELECTION) - failures}/{len(SELECTION)} programs "
          f"verified, compiled and ran cleanly")
    print(f"artefacts in {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
