"""Builds one self-contained sandbox per (variant, program, label) case.

The sandbox is what the judge agent is allowed to see: ``original.cbl``,
``modified.cbl``, ``intent.md`` (readable via the ``read_file`` MCP tool), plus
two internal JSON files (``testcases.json``, ``coverage.json``) that
``tools_server.py`` reads from to answer ``get_failing_testcases``/
``get_coverage`` -- never exposed as raw files to the agent. Nothing here
computes anything new: every value is pulled straight from artifacts already
produced by :mod:`testgen` and :mod:`mutgen`.

    python -m cobol_transformer.judge.prepare_case mutant1 lgacdb01 pprime
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Dict, List, Optional

from .ground_truth import DEFAULT_EXPERIMENT, EXPERIMENTS_ROOT, failing_test_ids

TRANSFORMED_DIR = "transformed"
TESTSUITES_DIR = "testsuites"
ROOT_REPORTS_DIR = "reports"
# Generated per-run data, not transformation logic -- lives alongside the
# other experiment-output directories (transformed/, experiments/,
# testsuites/, reports/, instrumented/), outside cobol_transformer/ and
# gitignored, never inside the source tree.
CASES_ROOT = os.path.join("judge_results", "cases")

_MUTANT_FILE = {"pprime": "P_prime.cbl", "pdprime": "P_double_prime.cbl"}


def case_dir(
    variant: str,
    program: str,
    label: str,
    cases_root: str = CASES_ROOT,
    experiment: str = DEFAULT_EXPERIMENT,
) -> str:
    return os.path.join(cases_root, experiment, variant, program, label)


def _load_manifest_blocks(manifest_path: str) -> Dict[str, dict]:
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)
    return {b["id"]: b for b in manifest.get("blocks", [])}


def _enrich_coverage(coverage: Optional[dict], blocks_by_id: Dict[str, dict]) -> dict:
    if not coverage:
        return {"blocks_hit": [], "block_coverage_pct": 0.0}
    hit = []
    for block_id in coverage.get("blocks_hit", []):
        block = blocks_by_id.get(block_id, {})
        hit.append({
            "id": block_id,
            "kind": block.get("kind", "unknown"),
            "name": block.get("name", block_id),
            "line_start": block.get("line_start"),
            "line_end": block.get("line_end"),
        })
    return {"blocks_hit": hit, "block_coverage_pct": coverage.get("block_coverage_pct", 0.0)}


def _mismatches(report_variables: dict) -> List[dict]:
    out = []
    for var, entry in (report_variables or {}).items():
        if entry.get("match") is False:
            out.append({
                "variable": var,
                "old_expected": entry.get("expected"),
                "actual_new": entry.get("actual", "unavailable"),
            })
    return out


def prepare_case(
    variant: str,
    program: str,
    label: str,
    cases_root: str = CASES_ROOT,
    force: bool = False,
    experiment: str = DEFAULT_EXPERIMENT,
) -> str:
    """Builds the sandbox, returns its directory path."""
    out_dir = case_dir(variant, program, label, cases_root, experiment)
    sandbox = os.path.join(out_dir, "sandbox")
    data_dir = os.path.join(out_dir, "_data")
    if force and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(sandbox, exist_ok=True)
    os.makedirs(data_dir, exist_ok=True)

    experiment_root = os.path.join(EXPERIMENTS_ROOT, experiment)

    # --- sandbox: the three files the agent is allowed to read ---
    shutil.copyfile(
        os.path.join(TRANSFORMED_DIR, f"{program}.cbl"),
        os.path.join(sandbox, "original.cbl"),
    )
    mutant_file = os.path.join(
        experiment_root, variant, "mutants", program, _MUTANT_FILE[label]
    )
    shutil.copyfile(mutant_file, os.path.join(sandbox, "modified.cbl"))
    intent_file = os.path.join(experiment_root, variant, "mutants", program, "intent.md")
    shutil.copyfile(intent_file, os.path.join(sandbox, "intent.md"))

    # --- internal data: what the MCP tools answer from ---
    test_ids = failing_test_ids(variant, program, label, experiment=experiment)
    mutation_reports_dir = os.path.join(
        experiment_root, variant, "mutation_runs", program, label, "reports", program
    )
    mutation_manifest_path = os.path.join(
        experiment_root, variant, "mutation_runs", program, label, "testsuite",
        "coverage_manifest.json",
    )
    original_manifest_path = os.path.join(TESTSUITES_DIR, program, "coverage_manifest.json")
    modified_blocks = _load_manifest_blocks(mutation_manifest_path)
    original_blocks = _load_manifest_blocks(original_manifest_path)

    testcases: Dict[str, dict] = {}
    coverage: Dict[str, dict] = {}
    for test_id in test_ids:
        with open(os.path.join(TESTSUITES_DIR, program, f"{test_id}.json"), "r", encoding="utf-8") as fh:
            testcase_src = json.load(fh)
        with open(os.path.join(mutation_reports_dir, f"{test_id}.report.json"), "r", encoding="utf-8") as fh:
            modified_report = json.load(fh)
        with open(os.path.join(ROOT_REPORTS_DIR, program, f"{test_id}.report.json"), "r", encoding="utf-8") as fh:
            original_report = json.load(fh)

        testcases[test_id] = {
            "description": testcase_src.get("description", ""),
            "initial_values": testcase_src.get("initial_values", {}),
            "mismatches": _mismatches(modified_report.get("variables")),
        }
        coverage[test_id] = {
            "original_run": _enrich_coverage(original_report.get("coverage"), original_blocks),
            "modified_run": _enrich_coverage(modified_report.get("coverage"), modified_blocks),
        }

    with open(os.path.join(data_dir, "testcases.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"testcases": testcases}, fh, indent=2)
        fh.write("\n")
    with open(os.path.join(data_dir, "coverage.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(coverage, fh, indent=2)
        fh.write("\n")

    return out_dir


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.judge.prepare_case",
        description="build one judge-agent sandbox for (variant, program, label)",
    )
    p.add_argument("variant")
    p.add_argument("program")
    p.add_argument("label", choices=["pprime", "pdprime"])
    p.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    p.add_argument("--cases-root", default=CASES_ROOT)
    p.add_argument("--force", action="store_true", help="rebuild even if the case already exists")
    args = p.parse_args(argv)

    try:
        out_dir = prepare_case(
            args.variant, args.program, args.label, args.cases_root, args.force, args.experiment
        )
    except FileNotFoundError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    print(f"case ready: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
