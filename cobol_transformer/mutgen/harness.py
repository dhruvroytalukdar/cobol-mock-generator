"""Evaluate a hand-authored mutant against a program's frozen test suite.

Reuses :mod:`testgen.run_and_report` unmodified: a mutant is compiled and run
against ``T`` by copying it into an isolated workspace that looks like a
``transformed/`` + ``testsuites/`` pair, then invoking the existing
checked-mode instrument/compile/run/compare CLI against that workspace. The
real ``testsuites/<program>`` directory is only ever read, never written to
(``run_and_report`` writes a ``coverage_manifest.json`` back into its test
directory, which is exactly why the test cases are copied rather than pointed
at directly).

    python -m cobol_transformer.mutgen.harness run lgacdb01 mutants/lgacdb01/P_prime.cbl pprime
    python -m cobol_transformer.mutgen.harness compare lgacdb01 pprime pdprime
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys
from typing import Dict, Optional, Set

from ..testgen import run_and_report


def _reset_dir(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


def _testcase_paths(testsuite_dir: str):
    return sorted(
        p for p in glob.glob(os.path.join(testsuite_dir, "*.json"))
        if not os.path.basename(p).startswith("coverage_manifest")
    )


def setup_workspace(
    program: str,
    mutant_path: str,
    label: str,
    base_dir: str = "mutation_runs",
    testsuite_dir: Optional[str] = None,
) -> str:
    """Build an isolated transformed/+testsuite/ pair for one mutant.

    Returns the workspace root (``<base_dir>/<program>/<label>``).
    """
    testsuite_dir = testsuite_dir or os.path.join("testsuites", program)
    workspace = os.path.join(base_dir, program, label)
    transformed_dir = os.path.join(workspace, "transformed")
    suite_dir = os.path.join(workspace, "testsuite")
    _reset_dir(transformed_dir)
    _reset_dir(suite_dir)

    shutil.copyfile(mutant_path, os.path.join(transformed_dir, f"{program}.cbl"))

    paths = _testcase_paths(testsuite_dir)
    if not paths:
        raise FileNotFoundError(f"no test cases found in {testsuite_dir}")
    for p in paths:
        shutil.copyfile(p, os.path.join(suite_dir, os.path.basename(p)))
    return workspace


class BrokenBuildError(RuntimeError):
    """A mutant run produced a compile or runtime failure, not a value mismatch.

    The documented hard constraint is that every test in every run must show
    ``compile_ok: true`` and ``run_ok: true`` -- a "failing" test must be a
    genuine semantic mismatch.  A mutant with a syntax error would otherwise
    make every test fail identically, trivially clearing the 50% threshold
    with no semantic content at all, and ``compare`` would report success on
    a comparison that never actually happened.
    """


def broken_build_tests(summary: dict) -> Set[str]:
    """Test IDs whose run did not even compile or execute, per ``suite_summary.json``."""
    return {
        r["test_id"] for r in summary["results"]
        if not r.get("compile_ok", True) or not r.get("run_ok", True)
    }


def run_mutant(
    program: str,
    mutant_path: str,
    label: str,
    base_dir: str = "mutation_runs",
    testsuite_dir: Optional[str] = None,
    ast_url: str = "http://127.0.0.1:4010",
    quiet: bool = True,
) -> dict:
    """Run the existing checked-mode pipeline against one mutant.

    Returns the ``suite_summary.json`` payload it produced.  Raises
    :class:`BrokenBuildError` if any test failed to compile or run, so a
    broken mutant is caught here rather than silently flowing into
    ``failing_tests.json`` as if its failures were meaningful.
    """
    workspace = setup_workspace(program, mutant_path, label, base_dir, testsuite_dir)
    argv = [
        os.path.join(workspace, "testsuite"),
        "--transformed-dir", os.path.join(workspace, "transformed"),
        "--instrumented-dir", os.path.join(workspace, "instrumented"),
        "--out", os.path.join(workspace, "reports"),
        "--program", program,
        "--ast-url", ast_url,
    ]
    if quiet:
        argv.append("--quiet")
    run_and_report.main(argv)

    summary_path = os.path.join(workspace, "reports", program, "suite_summary.json")
    with open(summary_path, "r", encoding="utf-8") as fh:
        summary = json.load(fh)

    broken = broken_build_tests(summary)
    if broken:
        raise BrokenBuildError(
            f"{program}/{label}: {len(broken)} test(s) failed to compile or run, "
            f"not a semantic mismatch: {', '.join(sorted(broken))}"
        )
    return summary


def failing_tests(summary: dict) -> Set[str]:
    return {r["test_id"] for r in summary["results"] if not r.get("all_match")}


def all_test_ids(testsuite_dir: str) -> Set[str]:
    ids: Set[str] = set()
    for p in _testcase_paths(testsuite_dir):
        with open(p, "r", encoding="utf-8") as fh:
            ids.add(json.load(fh)["test_id"])
    return ids


def compare(t_ids: Set[str], f_prime: Set[str], f_double_prime: Set[str]) -> dict:
    """Cardinalities and hard-constraint checks for the F'/F'' split.

    The hard constraints are (a) ``F'`` covers at least half of ``T``, and
    (b) every test that passed on ``P'`` (``T - F'``) fails on ``P''``. The
    soft goal is that ``|F'|`` and ``|F'' - F'|`` land close to a 50/50 split
    of ``T``.
    """
    total = len(t_ids)
    t_minus_f_prime = t_ids - f_prime
    missing = t_minus_f_prime - f_double_prime
    f_double_prime_minus_f_prime = f_double_prime - f_prime
    return {
        "total_tests": total,
        "f_prime": sorted(f_prime),
        "f_prime_count": len(f_prime),
        "f_prime_ratio": round(len(f_prime) / total, 4) if total else 0.0,
        "f_prime_meets_50pct": len(f_prime) * 2 >= total,
        "t_minus_f_prime": sorted(t_minus_f_prime),
        "f_double_prime": sorted(f_double_prime),
        "f_double_prime_count": len(f_double_prime),
        "t_minus_f_prime_subset_of_f_double_prime": not missing,
        "violating_tests": sorted(missing),
        "f_double_prime_minus_f_prime": sorted(f_double_prime_minus_f_prime),
        "f_double_prime_minus_f_prime_count": len(f_double_prime_minus_f_prime),
        "split_delta": abs(len(f_prime) - len(f_double_prime_minus_f_prime)),
    }


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.mutgen.harness",
        description="evaluate mutant COBOL sources against a program's frozen test suite",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run one mutant, report its failing tests")
    run_p.add_argument("program")
    run_p.add_argument("mutant_path")
    run_p.add_argument("label", help="e.g. pprime or pdprime")
    run_p.add_argument("--base-dir", default="mutation_runs")
    run_p.add_argument("--testsuite-dir", default=None)
    run_p.add_argument("--ast-url", default="http://127.0.0.1:4010")

    cmp_p = sub.add_parser("compare", help="compare two prior mutant runs' F sets")
    cmp_p.add_argument("program")
    cmp_p.add_argument("prime_label")
    cmp_p.add_argument("double_prime_label")
    cmp_p.add_argument("--base-dir", default="mutation_runs")
    cmp_p.add_argument("--testsuite-dir", default=None)

    args = p.parse_args(argv)

    if args.cmd == "run":
        try:
            summary = run_mutant(
                args.program, args.mutant_path, args.label,
                args.base_dir, args.testsuite_dir, args.ast_url,
            )
        except BrokenBuildError as exc:
            sys.stderr.write(str(exc) + "\n")
            return 2
        failing = failing_tests(summary)
        result_path = os.path.join(args.base_dir, args.program, args.label, "failing_tests.json")
        _write_json(result_path, {
            "program": args.program, "label": args.label,
            "passed": summary["passed"], "failed": summary["failed"],
            "failing_tests": sorted(failing),
        })
        print(f"{args.program}/{args.label}: {summary['failed']}/{summary['tests']} failing")
        print("failing:", ", ".join(sorted(failing)) or "(none)")
        return 0

    if args.cmd == "compare":
        testsuite_dir = args.testsuite_dir or os.path.join("testsuites", args.program)
        t_ids = all_test_ids(testsuite_dir)

        def _load_failing(label: str) -> Set[str]:
            path = os.path.join(args.base_dir, args.program, label, "failing_tests.json")
            with open(path, "r", encoding="utf-8") as fh:
                return set(json.load(fh)["failing_tests"])

        f_prime = _load_failing(args.prime_label)
        f_double_prime = _load_failing(args.double_prime_label)
        result = compare(t_ids, f_prime, f_double_prime)
        out_path = os.path.join(args.base_dir, args.program, "results.json")
        _write_json(out_path, result)
        print(json.dumps(result, indent=2))
        if not result["f_prime_meets_50pct"]:
            sys.stderr.write("HARD CONSTRAINT VIOLATED: |F'| does not reach 50% of T\n")
            return 1
        if not result["t_minus_f_prime_subset_of_f_double_prime"]:
            sys.stderr.write(
                "HARD CONSTRAINT VIOLATED: tests passing on P' do not all fail on P'': "
                + ", ".join(result["violating_tests"]) + "\n"
            )
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
