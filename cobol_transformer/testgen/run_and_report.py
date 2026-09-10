"""The repeatable regression + coverage run over a program's frozen test cases.

Stage 5.  Unlike the oracle, this touches neither the model nor the golden
values: it instruments in ``checked`` mode, compiles, runs, and reports what
matched and which blocks fired.  It can be re-run any time.

Two things are worth knowing about the numbers it produces.

*Suite-level coverage is the figure that matters.*  A single test case walks one
path; the point of having several is their union.  ``suite_summary.json``
therefore reports the union of every test's hit blocks, not an average.

*Line coverage here is a proxy, and a generous one.*  True line coverage would
need a probe on every line, which does not scale.  Instead each block carries
the line range it owns; covered lines are the **union** of the ranges of the
blocks that fired, minus the ranges of the blocks that did not -- a union
rather than a sum because IF blocks nest inside their paragraph and would
otherwise be counted twice, and a subtraction so that entering a long paragraph
does not credit branch bodies inside it that never ran.

It still reads high, because v1 models no block for an ``EVALUATE``/``WHEN``
body (phase 2), so those lines are credited to the enclosing paragraph whatever
path ran.  **Block coverage is the number to trust**; treat the line figure as
an upper bound until WHEN branches are tracked.

    python -m cobol_transformer.testgen.run_and_report testsuites/lgtestp1 \
        [--transformed-dir transformed] [--out reports]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

from ..errors import TransformError
from ..gnucobol.gnucobol_runner import GnuCobolRunner
from .cfg import Block, CoverageManifest, ProgramSources, load_program, manifest_for
from .instrumenter import TestCase, instrument
from .oracle_runner import build_and_run

COV_LINE = re.compile(r"^TC:COV:(?P<id>\S+)\s*$")
CHK_LINE = re.compile(
    r"^TC:CHK:(?P<var>[^:]+):MATCH=(?P<match>[YN]):ACTUAL=(?P<actual>.*)$"
)


def parse_coverage(stdout: str) -> List[str]:
    """Block IDs that fired, first-hit order, de-duplicated."""
    seen: Dict[str, bool] = {}
    for line in stdout.splitlines():
        m = COV_LINE.match(line.rstrip("\r"))
        if m:
            seen.setdefault(m.group("id"), True)
    return list(seen)


def parse_checks(stdout: str) -> Dict[str, Tuple[bool, str]]:
    """``{variable: (matched, actual)}``, last observation winning."""
    out: Dict[str, Tuple[bool, str]] = {}
    for line in stdout.splitlines():
        m = CHK_LINE.match(line.rstrip("\r"))
        if m:
            out[m.group("var").strip()] = (
                m.group("match") == "Y", m.group("actual").rstrip()
            )
    return out


def _line_set(blocks: List[Block]) -> Set[int]:
    covered: Set[int] = set()
    for b in blocks:
        if b.line_start and b.line_end >= b.line_start:
            covered.update(range(b.line_start, b.line_end + 1))
    return covered


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def coverage_report(manifest: CoverageManifest, hit_ids: List[str]) -> dict:
    by_id = manifest.by_id()
    known = [i for i in hit_ids if i in by_id]
    unknown = [i for i in hit_ids if i not in by_id]
    total_lines = _line_set(manifest.blocks)
    # A line counts as covered when a block that fired owns it and no block
    # that did not fire also owns it.  Without the subtraction, entering a long
    # paragraph would credit every line of the branch bodies nested inside it,
    # reporting high line coverage for a run that took none of those branches.
    hit_set = set(known)
    hit_lines = _line_set([by_id[i] for i in known]) - _line_set(
        [b for b in manifest.blocks if b.id not in hit_set]
    )
    report = {
        "blocks_hit": sorted(known),
        "blocks_total": len(manifest.blocks),
        "block_coverage_pct": _pct(len(known), len(manifest.blocks)),
        "lines_covered": len(hit_lines),
        "lines_total": len(total_lines),
        "line_coverage_pct": _pct(len(hit_lines), len(total_lines)),
    }
    if unknown:
        # A probe fired for a block the manifest does not know: the manifest
        # and the instrumented source have drifted apart.
        report["blocks_unknown"] = sorted(unknown)
    return report


def run_testcase(
    testcase: TestCase,
    sources: ProgramSources,
    manifest: CoverageManifest,
    out_dir: str,
    runner: GnuCobolRunner,
    timeout: int = 60,
    extra_flags: Optional[List[str]] = None,
) -> dict:
    """Instrument, compile, run and score one frozen test case."""
    report = {
        "test_id": testcase.test_id,
        "program": testcase.program or sources.program,
        "description": testcase.description,
        "compile_ok": False,
        "run_ok": False,
        "returncode": None,
        "variables": {},
        "all_match": False,
    }
    instrumented = instrument(
        sources.text, testcase, sources.symbols, mode="checked", manifest=manifest
    )
    source_path = os.path.join(out_dir, f"{testcase.test_id}.cbl")
    instrumented.write(source_path)
    report["source"] = os.path.relpath(source_path).replace("\\", "/")
    if instrumented.variables_skipped:
        report["variables_not_compared"] = instrumented.variables_skipped

    compiled, ran = build_and_run(source_path, runner, timeout, extra_flags)
    report["compile_ok"] = compiled.ok
    if not compiled.ok:
        report["error"] = (compiled.stderr or compiled.stdout)[:2000]
        return report
    assert ran is not None
    # Only a negative code (the runner timed out) means the run failed.  A
    # non-zero exit is ordinary program state here -- RETURN-CODE is a field
    # the program writes, and one corpus program leaves it as four spaces and
    # so exits 32 after a completely normal run.  It is recorded, not judged.
    report["returncode"] = ran.returncode
    report["run_ok"] = ran.returncode >= 0
    if not report["run_ok"]:
        report["error"] = (ran.stderr or ran.stdout)[:2000]
        return report

    checks = parse_checks(ran.stdout)
    expected = testcase.expected_values or {}
    variables: Dict[str, dict] = {}
    for name in testcase.variables_to_check:
        entry = {"expected": expected.get(name)}
        if name in checks:
            matched, actual = checks[name]
            entry["actual"] = actual
            entry["match"] = matched
        elif name in instrumented.variables_skipped:
            entry["match"] = None
            entry["not_compared"] = instrumented.variables_skipped[name]
        else:
            entry["match"] = None
            entry["not_compared"] = (
                "the program produced no check line for this variable"
            )
        variables[name] = entry
    report["variables"] = variables
    compared = [v for v in variables.values() if v.get("match") is not None]
    if not testcase.variables_to_check:
        # A coverage-only case asserts nothing about values, so reaching the
        # end of the run is the whole of its result.
        report["all_match"] = report["run_ok"]
    else:
        # Requiring at least one comparison keeps a case whose checks all
        # silently failed to run from being reported as a pass.
        report["all_match"] = bool(compared) and all(v["match"] for v in compared)
    report["coverage"] = coverage_report(manifest, parse_coverage(ran.stdout))
    return report


def summarize(program: str, reports: List[dict], manifest: CoverageManifest) -> dict:
    """Union coverage plus a pass/fail row per test."""
    union: List[str] = []
    seen: Set[str] = set()
    for r in reports:
        for block_id in r.get("coverage", {}).get("blocks_hit", []):
            if block_id not in seen:
                seen.add(block_id)
                union.append(block_id)
    by_id = manifest.by_id()
    never = [b.id for b in manifest.blocks if b.id not in seen]
    return {
        "program": program,
        "tests": len(reports),
        "passed": sum(1 for r in reports if r.get("all_match")),
        "failed": sum(1 for r in reports if not r.get("all_match")),
        "results": [
            {
                "test_id": r["test_id"],
                "description": r.get("description", ""),
                "compile_ok": r.get("compile_ok"),
                "run_ok": r.get("run_ok"),
                "all_match": r.get("all_match"),
                "block_coverage_pct": r.get("coverage", {}).get("block_coverage_pct"),
            }
            for r in reports
        ],
        "suite_coverage": {
            **coverage_report(manifest, union),
            "blocks_never_hit": never,
        },
    }


def _write_json(path: str, payload: dict) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.testgen.run_and_report",
        description="run a program's frozen test cases and report coverage",
    )
    p.add_argument("test_dir", help="testsuites/<program> directory")
    p.add_argument("--transformed-dir", default="transformed")
    p.add_argument("--instrumented-dir", default="instrumented")
    p.add_argument("--out", default="reports")
    p.add_argument("--program", help="defaults to the test directory's name")
    p.add_argument("--ast-url", default="http://127.0.0.1:4010")
    p.add_argument("--run-timeout", type=int, default=60)
    p.add_argument("--gnucobol-flags", default="")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    program = args.program or os.path.basename(os.path.normpath(args.test_dir))
    try:
        sources = load_program(args.transformed_dir, program)
        manifest = manifest_for(sources, args.ast_url)
    except (FileNotFoundError, TransformError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    manifest.write(os.path.join(args.test_dir, "coverage_manifest.json"))

    paths = sorted(
        q for q in glob.glob(os.path.join(args.test_dir, "*.json"))
        if not os.path.basename(q).startswith("coverage_manifest")
    )
    if not paths:
        sys.stderr.write(f"error: no test cases in {args.test_dir}\n")
        return 2

    out_dir = os.path.join(args.instrumented_dir, program, "checked")
    report_dir = os.path.join(args.out, program)
    runner = GnuCobolRunner()
    flags = args.gnucobol_flags.split() or None
    reports: List[dict] = []
    unfrozen: List[str] = []

    for path in paths:
        testcase = TestCase.load(path)
        if not testcase.is_frozen:
            unfrozen.append(testcase.test_id)
            continue
        try:
            report = run_testcase(
                testcase, sources, manifest, out_dir, runner, args.run_timeout, flags
            )
        except TransformError as exc:
            report = {
                "test_id": testcase.test_id, "program": program,
                "compile_ok": False, "run_ok": False, "all_match": False,
                "error": str(exc), "variables": {},
            }
        reports.append(report)
        _write_json(os.path.join(report_dir, f"{testcase.test_id}.report.json"), report)
        if not args.quiet:
            cov = report.get("coverage", {})
            status = "PASS" if report.get("all_match") else "FAIL"
            print(
                f"{report['test_id']}: {status}  "
                f"blocks {len(cov.get('blocks_hit', []))}/{cov.get('blocks_total', 0)}"
                f" ({cov.get('block_coverage_pct', 0)}%)"
            )

    for test_id in unfrozen:
        sys.stderr.write(
            f"{test_id}: skipped - no expected_values; run oracle_runner first\n"
        )
    if not reports:
        return 2

    summary = summarize(program, reports, manifest)
    if unfrozen:
        summary["skipped_unfrozen"] = unfrozen
    _write_json(os.path.join(report_dir, "suite_summary.json"), summary)
    if not args.quiet:
        suite = summary["suite_coverage"]
        print(
            f"{program}: {summary['passed']}/{summary['tests']} passed; "
            f"suite blocks {len(suite['blocks_hit'])}/{suite['blocks_total']} "
            f"({suite['block_coverage_pct']}%), "
            f"lines {suite['lines_covered']}/{suite['lines_total']} "
            f"({suite['line_coverage_pct']}%)"
        )
    return 0 if summary["failed"] == 0 and not unfrozen else 1


if __name__ == "__main__":
    raise SystemExit(main())
