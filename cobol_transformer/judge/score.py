"""Scores a judge run's verdicts.json against ground_truth.py.

    python -m cobol_transformer.judge.score --variant mutant1 --program lgacdb01 \\
        --label pprime --condition treatment --backend claude-cli --model claude-haiku-4-5

    python -m cobol_transformer.judge.score --all   # walk every results/ dir found
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional

from .ground_truth import BUG_TRIGGERED, DEFAULT_EXPERIMENT, OBSOLETE, ground_truth
from .run_judge import RESULTS_ROOT


def _load_verdicts(output_dir: str) -> Dict[str, str]:
    path = os.path.join(output_dir, "verdicts.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = {}
    for entry in data.get("verdicts", []):
        test_id = entry.get("test_id")
        verdict = entry.get("verdict")
        if test_id is not None and verdict is not None:
            out[test_id] = verdict
    return out


def score_one(
    variant: str, program: str, label: str, output_dir: str, experiment: str = DEFAULT_EXPERIMENT
) -> dict:
    truth = ground_truth(variant, program, label, experiment=experiment)
    predicted = _load_verdicts(output_dir)

    rows = []
    for test_id, true_label in truth.items():
        pred_label = predicted.get(test_id, "MISSING")
        rows.append((test_id, true_label, pred_label))

    total = len(rows)
    correct = sum(1 for _, t, p in rows if t == p)

    confusion = {
        (OBSOLETE, OBSOLETE): 0, (OBSOLETE, BUG_TRIGGERED): 0, (OBSOLETE, "MISSING"): 0,
        (BUG_TRIGGERED, OBSOLETE): 0, (BUG_TRIGGERED, BUG_TRIGGERED): 0, (BUG_TRIGGERED, "MISSING"): 0,
    }
    for _, t, p in rows:
        confusion[(t, p)] = confusion.get((t, p), 0) + 1

    n_obsolete = sum(1 for _, t, _ in rows if t == OBSOLETE)
    n_bug = sum(1 for _, t, _ in rows if t == BUG_TRIGGERED)
    false_bug_rate = (
        confusion[(OBSOLETE, BUG_TRIGGERED)] / n_obsolete if n_obsolete else None
    )
    bug_recall = confusion[(BUG_TRIGGERED, BUG_TRIGGERED)] / n_bug if n_bug else None
    predicted_bug_total = sum(1 for _, _, p in rows if p == BUG_TRIGGERED)
    bug_precision = (
        confusion[(BUG_TRIGGERED, BUG_TRIGGERED)] / predicted_bug_total
        if predicted_bug_total else None
    )

    return {
        "experiment": experiment, "variant": variant, "program": program, "label": label,
        "total": total, "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "n_obsolete": n_obsolete, "n_bug_triggered": n_bug,
        "false_bug_rate": round(false_bug_rate, 4) if false_bug_rate is not None else None,
        "bug_recall": round(bug_recall, 4) if bug_recall is not None else None,
        "bug_precision": round(bug_precision, 4) if bug_precision is not None else None,
        "confusion": {f"{t}->{p}": n for (t, p), n in confusion.items()},
        "rows": [{"test_id": tid, "truth": t, "predicted": p} for tid, t, p in rows],
    }


def _discover_result_dirs(results_root: str = RESULTS_ROOT) -> List[dict]:
    """Every leaf directory under results/ that contains a verdicts.json.

    Path shape: results/<experiment>/<variant>/<program>/<label>/<condition>/
    <backend>-<model>/verdicts.json.
    """
    found = []
    for dirpath, _dirnames, filenames in os.walk(results_root):
        if "verdicts.json" not in filenames:
            continue
        rel = os.path.relpath(dirpath, results_root)
        parts = rel.split(os.sep)
        if len(parts) != 6:
            continue
        experiment, variant, program, label, condition, backend_model = parts
        found.append({
            "experiment": experiment, "variant": variant, "program": program, "label": label,
            "condition": condition, "backend_model": backend_model,
            "output_dir": dirpath,
        })
    return found


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.judge.score",
        description="score a judge run's verdicts.json against ground truth",
    )
    p.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    p.add_argument("--variant")
    p.add_argument("--program")
    p.add_argument("--label", choices=["pprime", "pdprime"])
    p.add_argument("--condition", choices=["baseline", "treatment", "restricted"])
    p.add_argument("--backend", default="claude-cli")
    p.add_argument("--model", default="claude-haiku-4-5")
    p.add_argument("--all", action="store_true", help="score every run found under results/ (all experiments)")
    args = p.parse_args(argv)

    if args.all:
        summaries = []
        for case in _discover_result_dirs():
            try:
                result = score_one(
                    case["variant"], case["program"], case["label"], case["output_dir"],
                    experiment=case["experiment"],
                )
            except FileNotFoundError as exc:
                print(f"skip {case['output_dir']}: {exc}")
                continue
            result["condition"] = case["condition"]
            result["backend_model"] = case["backend_model"]
            result.pop("rows", None)
            summaries.append(result)
        print(json.dumps(summaries, indent=2))
        return 0

    if not (args.variant and args.program and args.label and args.condition):
        p.error("--variant/--program/--label/--condition are required unless --all is passed")

    model_tag = args.model.replace("/", "_")
    output_dir = os.path.join(
        RESULTS_ROOT, args.experiment, args.variant, args.program, args.label,
        args.condition, f"{args.backend}-{model_tag}",
    )
    result = score_one(args.variant, args.program, args.label, output_dir, experiment=args.experiment)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
