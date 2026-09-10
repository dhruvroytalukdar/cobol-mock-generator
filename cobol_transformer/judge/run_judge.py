"""CLI entry point: prepares a case, runs the judge agent in one of two
conditions, and writes verdicts.json + a transcript for :mod:`score` to
consume afterwards.

    python -m cobol_transformer.judge.run_judge \\
        --variant mutant1 --program lgacdb01 --label pprime \\
        --condition treatment --backend claude-cli \\
        --model claude-haiku-4-5 --effort low \\
        --prompt-file prompts/obs_vs_bug_v2.md

Three conditions:

* ``baseline`` -- no MCP server, no user prompt file. Everything the agent
  could possibly use (original/modified source, intent, failing-test
  mismatches) is inlined into one text blob; a bare one-line system prompt
  asks for JSON back. This is deliberately the worst-case condition.
* ``treatment`` -- the MCP tool server is attached and the user's own
  classification prompt file (their contribution) is sent verbatim as the
  task prompt; the harness-level system prompt is kept to one generic line.
* ``restricted`` -- an ablation between the two: the MCP server is attached
  and a user-supplied prompt file is used, but the agent may only call
  ``read_file``/``write_file`` -- ``get_failing_testcases`` and
  ``get_coverage`` are withheld. Since there is then no tool to fetch the
  failing testcases, they are pushed directly into the task prompt (the
  same data ``baseline`` inlines), and no coverage data is given at all.
  This isolates whether ``get_failing_testcases``/``get_coverage`` and a
  guided prompt -- as opposed to just having read/write access -- are what
  drive treatment's accuracy.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Optional

from .backends import ClaudeCLIBackend, JudgeBackend, LiteLLMBackend
from .ground_truth import DEFAULT_EXPERIMENT
from .prepare_case import case_dir as case_dir_path
from .prepare_case import prepare_case

# Generated per-run data, not transformation logic -- see prepare_case.py's
# CASES_ROOT comment for why this lives outside cobol_transformer/.
RESULTS_ROOT = os.path.join("judge_results", "results")

BASELINE_SYSTEM_PROMPT = (
    "You are a classification assistant. Respond only with the JSON object requested."
)
TREATMENT_SYSTEM_PROMPT = (
    "You are an autonomous agent with access to tools. Use them as needed to "
    "complete the user's task, then record your final answer using the "
    "write_file tool exactly as instructed."
)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _build_baseline_prompt(case_path: str) -> str:
    sandbox = os.path.join(case_path, "sandbox")
    data_dir = os.path.join(case_path, "_data")
    original = _read(os.path.join(sandbox, "original.cbl"))
    modified = _read(os.path.join(sandbox, "modified.cbl"))
    intent = _read(os.path.join(sandbox, "intent.md"))
    with open(os.path.join(data_dir, "testcases.json"), "r", encoding="utf-8") as fh:
        testcases = json.load(fh)

    return f"""You are given a COBOL program (ORIGINAL), a modified version (MODIFIED), a \
natural-language description of an intended change (INTENT — describing only \
the authorized change; MODIFIED may go further than what it describes), and a \
set of testcases that fail against MODIFIED. For each failing testcase, decide \
whether it fails because it is OBSOLETE (the intent legitimately changed that \
behavior, so the testcase's old expectation is simply stale) or because of a \
BUG_TRIGGERED (the modification did something the intent does not authorize).

=== INTENT ===
{intent}

=== ORIGINAL ===
{original}

=== MODIFIED ===
{modified}

=== FAILING TESTCASES ===
{json.dumps(testcases, indent=2)}

Respond with ONLY a single JSON object, no other text, in exactly this shape:
{{"verdicts": [{{"test_id": "<id>", "verdict": "OBSOLETE"|"BUG_TRIGGERED", "justification": "<1-2 sentences>"}}]}}
"""


def _load_testcases_block(case_path: str) -> str:
    data_dir = os.path.join(case_path, "_data")
    with open(os.path.join(data_dir, "testcases.json"), "r", encoding="utf-8") as fh:
        testcases = json.load(fh)
    return json.dumps(testcases, indent=2)


def _build_restricted_prompt(prompt_file: str, case_path: str) -> str:
    template = _read(prompt_file)
    testcases_block = _load_testcases_block(case_path)
    if "{{FAILING_TESTCASES_JSON}}" in template:
        return template.replace("{{FAILING_TESTCASES_JSON}}", testcases_block)
    # Prompt file didn't use the placeholder -- append instead of dropping the data.
    return f"{template}\n\n=== FAILING TESTCASES ===\n{testcases_block}\n"


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _make_backend(args: argparse.Namespace) -> JudgeBackend:
    if args.backend == "claude-cli":
        return ClaudeCLIBackend(model=args.model, effort=args.effort or "low")
    if args.backend == "litellm":
        return LiteLLMBackend(model=args.model, reasoning_effort=args.effort)
    raise ValueError(f"unknown backend {args.backend!r}")


def run(args: argparse.Namespace) -> int:
    case_path = prepare_case(args.variant, args.program, args.label, experiment=args.experiment)
    backend = _make_backend(args)

    model_tag = args.model.replace("/", "_")
    output_dir = os.path.join(
        RESULTS_ROOT, args.experiment, args.variant, args.program, args.label,
        args.condition, f"{args.backend}-{model_tag}",
    )
    os.makedirs(output_dir, exist_ok=True)

    allowed_mcp_tools: Optional[list] = None
    if args.condition == "baseline":
        system_prompt = BASELINE_SYSTEM_PROMPT
        task_prompt = _build_baseline_prompt(case_path)
        tools_enabled = False
    elif args.condition == "restricted":
        if not args.prompt_file:
            sys.stderr.write("error: --prompt-file is required for --condition restricted\n")
            return 2
        system_prompt = TREATMENT_SYSTEM_PROMPT
        task_prompt = _build_restricted_prompt(args.prompt_file, case_path)
        tools_enabled = True
        allowed_mcp_tools = ["read_file", "write_file"]
    else:
        if not args.prompt_file:
            sys.stderr.write("error: --prompt-file is required for --condition treatment\n")
            return 2
        system_prompt = TREATMENT_SYSTEM_PROMPT
        task_prompt = _read(args.prompt_file)
        tools_enabled = True

    result = backend.run(
        system_prompt=system_prompt,
        task_prompt=task_prompt,
        case_dir=case_path,
        output_dir=output_dir,
        tools_enabled=tools_enabled,
        allowed_mcp_tools=allowed_mcp_tools,
    )

    with open(os.path.join(output_dir, "transcript.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for entry in result.transcript:
            fh.write(json.dumps(entry, default=str) + "\n")
        if not result.transcript:
            fh.write(json.dumps({"raw_output": result.raw_output, "error": result.error}) + "\n")

    if result.error:
        sys.stderr.write(f"error: {result.error}\n")
        return 1

    verdicts_path = os.path.join(output_dir, "verdicts.json")
    if args.condition == "baseline":
        # No write_file tool exists in this condition -- the agent's final
        # message *is* the answer; parse and persist it the same way a
        # treatment run's write_file call would have.
        parsed = _extract_json(result.raw_output)
        if parsed is None:
            sys.stderr.write("error: could not parse JSON from baseline agent output\n")
            with open(os.path.join(output_dir, "raw_output.txt"), "w", encoding="utf-8") as fh:
                fh.write(result.raw_output)
            return 1
        with open(verdicts_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(parsed, fh, indent=2)
            fh.write("\n")
    elif not os.path.exists(verdicts_path):
        sys.stderr.write(
            "warning: treatment run finished but no verdicts.json was written via write_file\n"
        )
        return 1

    print(f"done: {output_dir}")
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.judge.run_judge",
        description="run the OBSOLETE/BUG_TRIGGERED judge agent on one case",
    )
    p.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    p.add_argument("--variant", required=True)
    p.add_argument("--program", required=True)
    p.add_argument("--label", required=True, choices=["pprime", "pdprime"])
    p.add_argument("--condition", required=True, choices=["baseline", "treatment", "restricted"])
    p.add_argument("--backend", default="claude-cli", choices=["claude-cli", "litellm"])
    p.add_argument("--model", default="claude-haiku-4-5")
    p.add_argument("--effort", default=None, help="claude-cli: --effort value; litellm: reasoning_effort")
    p.add_argument("--prompt-file", default=None, help="required for --condition treatment")
    args = p.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
