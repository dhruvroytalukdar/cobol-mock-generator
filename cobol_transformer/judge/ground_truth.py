"""Ground-truth OBSOLETE/BUG_TRIGGERED labels for the judge experiment.

Derived entirely from ``experiments/<experiment>/<variant>/mutation_runs/
<program>/results.json``, which already records F' and F'' for every program
(see :mod:`cobol_transformer.mutgen.harness`). The rule:

* Judging P' (``label="pprime"``): every test in F' is OBSOLETE by
  construction -- P' was built and verified to be intent-consistent with no
  accidental bugs.
* Judging P'' (``label="pdprime"``): the failing set is F'' (empirically
  equal to the whole suite T in this corpus); a test is OBSOLETE if it's also
  in F', and BUG_TRIGGERED if it's only in F'' (i.e. in F'' - F').

``experiment`` names which study this case belongs to -- e.g.
``modification_quantity`` (does the *size* of an authorized diff change
judge accuracy? variants ``mutant1``/``mutant2``) vs. ``intent_quality``
(does the *quality* of the accompanying intent text change judge accuracy,
for the exact same code change? variants ``detailed``/``vague``). It is
purely a namespacing axis -- the OBSOLETE/BUG_TRIGGERED derivation rule above
is identical regardless of which experiment a case belongs to.

    python -m cobol_transformer.judge.ground_truth mutant1 lgacdb01 pdprime
    python -m cobol_transformer.judge.ground_truth detailed lgicdb01 pdprime --experiment intent_quality
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

OBSOLETE = "OBSOLETE"
BUG_TRIGGERED = "BUG_TRIGGERED"

EXPERIMENTS_ROOT = "experiments"
DEFAULT_EXPERIMENT = "modification_quantity"


def _results_path(
    variant: str, program: str, root: str, experiment: str = DEFAULT_EXPERIMENT
) -> str:
    return os.path.join(root, experiment, variant, "mutation_runs", program, "results.json")


def load_results(
    variant: str,
    program: str,
    root: str = EXPERIMENTS_ROOT,
    experiment: str = DEFAULT_EXPERIMENT,
) -> dict:
    path = _results_path(variant, program, root, experiment)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ground_truth(
    variant: str,
    program: str,
    label: str,
    root: str = EXPERIMENTS_ROOT,
    experiment: str = DEFAULT_EXPERIMENT,
) -> Dict[str, str]:
    """``{test_id: "OBSOLETE"|"BUG_TRIGGERED"}`` for one (variant, program, label)."""
    results = load_results(variant, program, root, experiment)
    f_prime = set(results["f_prime"])
    if label == "pprime":
        return {test_id: OBSOLETE for test_id in f_prime}
    if label == "pdprime":
        f_double_prime = set(results["f_double_prime"])
        return {
            test_id: (OBSOLETE if test_id in f_prime else BUG_TRIGGERED)
            for test_id in f_double_prime
        }
    raise ValueError(f"unknown label {label!r}, expected 'pprime' or 'pdprime'")


def failing_test_ids(
    variant: str,
    program: str,
    label: str,
    root: str = EXPERIMENTS_ROOT,
    experiment: str = DEFAULT_EXPERIMENT,
) -> List[str]:
    """The exact set of test ids a case for (variant, program, label) covers."""
    results = load_results(variant, program, root, experiment)
    ids = results["f_prime"] if label == "pprime" else results["f_double_prime"]
    return sorted(ids)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.judge.ground_truth",
        description="print the OBSOLETE/BUG_TRIGGERED ground truth for one case",
    )
    p.add_argument("variant")
    p.add_argument("program")
    p.add_argument("label", choices=["pprime", "pdprime"])
    p.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    p.add_argument("--root", default=EXPERIMENTS_ROOT)
    args = p.parse_args(argv)

    try:
        labels = ground_truth(args.variant, args.program, args.label, args.root, args.experiment)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    print(json.dumps(labels, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
