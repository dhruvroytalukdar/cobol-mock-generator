"""Sequential batch runner for the judge, in visible chunks.

    python -m cobol_transformer.judge.run_batch \
        --condition restricted --prompt-file prompts/obs_vs_bug_restricted.md \
        --batch-size 20

Walks every (experiment, variant, program, label) case across the four
experiment variants this project's mutation study produced --
``modification_quantity/{mutant1,mutant2}`` and
``intent_quality/{detailed,vague}`` -- ten programs each, both labels
(``pprime``, ``pdprime``): 80 cases by default. Runs ``run_judge.run()`` for
each one, one at a time (never in parallel -- this shares the same
account-level ``claude -p`` session quota every other headless call in this
project draws on), printing a progress line per case. A case that errors is
logged and skipped rather than aborting the whole run.

Ground truth is already known (see ``ground_truth.py``), so each case is
scored immediately after it finishes and the running accuracy is printed
alongside progress -- no need to wait for the whole batch to call
``score.py`` separately, though that still works afterwards for the
combined view across conditions.
"""
from __future__ import annotations

import argparse
import io
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from typing import List, Optional, Tuple

from . import run_judge, score

PROGRAMS = [
    "lgacdb01", "lgacdb02", "lgapdb01", "lgapvs01", "lgdpdb01",
    "lgicdb01", "lgipdb01", "lgucdb01", "lgupdb01", "lgwebst5",
]
DEFAULT_CASE_AXES = [
    ("modification_quantity", "mutant1"),
    ("modification_quantity", "mutant2"),
    ("intent_quality", "detailed"),
    ("intent_quality", "vague"),
]
LABELS = ["pprime", "pdprime"]


def build_case_list(
    axes: List[Tuple[str, str]] = DEFAULT_CASE_AXES,
    programs: List[str] = PROGRAMS,
    labels: List[str] = LABELS,
) -> List[Tuple[str, str, str, str]]:
    """``(experiment, variant, program, label)`` tuples, in a stable order."""
    return [
        (experiment, variant, program, label)
        for experiment, variant in axes
        for program in programs
        for label in labels
    ]


def _bar(done: int, total: int, width: int = 24) -> str:
    filled = int(width * done / total) if total else width
    return "#" * filled + "-" * (width - filled)


def run_one(
    experiment: str, variant: str, program: str, label: str, base_args: argparse.Namespace,
) -> dict:
    ns = argparse.Namespace(**vars(base_args))
    ns.experiment, ns.variant, ns.program, ns.label = experiment, variant, program, label

    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            rc = run_judge.run(ns)
    except Exception as exc:  # noqa: BLE001 -- one bad case must not kill the batch
        return {"ok": False, "error": f"exception: {exc}"}

    if rc != 0:
        err = buf_err.getvalue().strip() or buf_out.getvalue().strip()
        return {"ok": False, "error": err or f"run_judge exited {rc}"}

    model_tag = ns.model.replace("/", "_")
    output_dir = os.path.join(
        run_judge.RESULTS_ROOT, experiment, variant, program, label,
        ns.condition, f"{ns.backend}-{model_tag}",
    )
    try:
        result = score.score_one(variant, program, label, output_dir, experiment=experiment)
    except Exception as exc:  # noqa: BLE001 -- verdicts.json exists but didn't score; still a success
        return {"ok": True, "scored": False, "error": f"scoring failed: {exc}"}

    return {
        "ok": True, "scored": True, "accuracy": result["accuracy"],
        "correct": result["correct"], "total": result["total"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.judge.run_batch",
        description="run the judge across every case, sequentially, in visible batches",
    )
    p.add_argument("--condition", required=True, choices=["baseline", "treatment", "restricted"])
    p.add_argument("--backend", default="claude-cli", choices=["claude-cli", "litellm"])
    p.add_argument("--model", default="claude-haiku-4-5")
    p.add_argument("--effort", default="low")
    p.add_argument("--prompt-file", default=None)
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--only-label", choices=["pprime", "pdprime"], default=None)
    p.add_argument("--start-at", type=int, default=0, help="skip the first N cases (resume)")
    args = p.parse_args(argv)

    labels = [args.only_label] if args.only_label else LABELS
    cases = build_case_list(labels=labels)[args.start_at:]
    total = len(cases)
    n_batches = (total + args.batch_size - 1) // args.batch_size

    base_args = argparse.Namespace(
        condition=args.condition, backend=args.backend, model=args.model,
        effort=args.effort, prompt_file=args.prompt_file,
    )

    print(
        f"=== {total} cases, {n_batches} batch(es) of up to {args.batch_size}, "
        f"condition={args.condition} backend={args.backend} model={args.model} ===\n",
        flush=True,
    )

    n_ok = n_err = n_scored = 0
    sum_correct = sum_total = 0
    failures = []
    t_start = time.time()

    for batch_idx in range(n_batches):
        batch = cases[batch_idx * args.batch_size: (batch_idx + 1) * args.batch_size]
        print(f"--- batch {batch_idx + 1}/{n_batches} ({len(batch)} cases) ---", flush=True)
        for i, (experiment, variant, program, label) in enumerate(batch, start=1):
            overall_i = batch_idx * args.batch_size + i
            t0 = time.time()
            r = run_one(experiment, variant, program, label, base_args)
            dt = time.time() - t0
            tag = f"{experiment}/{variant}/{program}/{label}"
            prog = f"[{overall_i:>3}/{total}] {_bar(overall_i, total)}"

            if not r.get("ok"):
                n_err += 1
                failures.append((tag, r.get("error", "unknown error")))
                print(f"{prog}  {tag:<48} FAIL  ({dt:5.1f}s)  {r.get('error', '')[:120]}", flush=True)
                continue

            n_ok += 1
            if r.get("scored") and r["total"]:
                n_scored += 1
                sum_correct += r["correct"]
                sum_total += r["total"]
                print(
                    f"{prog}  {tag:<48} OK    ({dt:5.1f}s)  "
                    f"{r['correct']}/{r['total']} correct ({r['accuracy'] * 100:.0f}%)",
                    flush=True,
                )
            else:
                print(
                    f"{prog}  {tag:<48} OK    ({dt:5.1f}s)  "
                    f"(no scoring: {r.get('error', 'no ground-truth cases')[:80]})",
                    flush=True,
                )
        print(flush=True)

    elapsed = time.time() - t_start
    print("=== summary ===")
    print(f"cases run : {total}")
    print(f"succeeded : {n_ok}")
    print(f"failed    : {n_err}")
    if sum_total:
        print(
            f"aggregate accuracy (scored cases): {sum_correct}/{sum_total} "
            f"({100 * sum_correct / sum_total:.1f}%) across {n_scored} cases"
        )
    print(f"elapsed   : {elapsed / 60:.1f} min")
    if failures:
        print("\nfailed cases:")
        for tag, err in failures:
            print(f"  - {tag}: {err[:200]}")

    return 0 if n_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
