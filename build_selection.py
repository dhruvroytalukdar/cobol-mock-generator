#!/usr/bin/env python3
"""Transform, verify, compile and run the ten selected GenApp programs.

Scope: only programs the AST backend can parse.  Five GenApp programs are
excluded because the Z Open Editor language server refuses to emit an AST for
them at all -- its CICS validator rejects ``SEND TEXT ... WAIT`` and ``ASIS``
without ``TERMINAL`` (lgicvs01, lgipvs01, lgsetup, lgstsq, lgtestc1).  The
lexical fallback still handles those, but they are out of scope here.

Selection: the five largest AST-parsable programs by line count, then the next
five.  The corpus has no program between 328 and 535 lines once the excluded
ones are removed, so the second group is the closest available tier rather than
a literal ~500 lines.

Every program here must use the ``ast`` backend; falling back would mean the
run silently left the AST path untested, so it is treated as a failure.

Outputs land in ``transformed/``: the ``.cbl`` itself, a JSON manifest, a
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
SRC = os.path.join(REPO, "genapp-files", "src")
OUT = os.path.join(REPO, "transformed")

#: Programs the language server declines to parse; handled by the lexical
#: fallback but deliberately out of scope for this selection.
AST_EXCLUDED = ["lgicvs01", "lgipvs01", "lgsetup", "lgstsq", "lgtestc1"]

LARGEST = ["lgipdb01", "lgwebst5", "lgapdb01", "lgupdb01", "lgacdb01"]
MIDSIZE = ["lgtestp4", "lgtestp1", "lgtestp2", "lgtestp3", "lgicdb01"]
SELECTION = LARGEST + MIDSIZE


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    runner = GnuCobolRunner()
    opts = PipelineOptions()
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
        comp = runner.compile(out_cbl, os.path.join(OUT, name))
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
