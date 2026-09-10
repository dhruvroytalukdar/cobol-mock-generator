"""Stage 1: drive the ``claude`` CLI headlessly to write test cases.

One subprocess per program, sequentially, with file access scoped to that
program's own ``testsuites/<program>/`` directory so a run cannot touch the
COBOL sources or another program's suite.

Generated files are validated before being accepted.  A test case naming a
variable the program does not have, or a value that will not fit its PICTURE,
is rejected here with a clear message rather than surfacing later as a COBOL
compile error inside generated code.  Producing fewer than ``--min-tests``
cases is itself reported as a failure, so the floor is enforced on the way out
and not merely requested in the prompt.

    python -m cobol_transformer.testgen.generate_testcases transformed \\
        [--out testsuites] [--claude-bin claude] [--min-tests 15] \\
        [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

from ..errors import TransformError
from .cfg import load_program
from .instrumenter import TestCase
from .literal_format import LiteralError, pic_info_to_move_literal
from .prompt_builder import DEFAULT_MIN_TESTS, build_prompt, write_prompt
from .variable_context import build_context


def validate_testcase(testcase: TestCase, sources) -> List[str]:
    """Problems that would make ``testcase`` unusable, as readable messages."""
    problems: List[str] = []
    if not testcase.initial_values and not testcase.variables_to_check:
        problems.append("neither initial_values nor variables_to_check is set")
    for name, value in testcase.initial_values.items():
        sym = sources.symbols.get(name)
        if sym is None:
            problems.append(f"initial_values.{name}: no such variable")
            continue
        pic = sym.pic if sym.pic_text else None
        try:
            pic_info_to_move_literal(pic, str(value))
        except LiteralError as exc:
            problems.append(f"initial_values.{name}: {exc}")
    for name in testcase.variables_to_check:
        if sources.symbols.get(name) is None:
            problems.append(f"variables_to_check: {name} is not a variable")
    if testcase.expected_values:
        problems.append(
            "expected_values must not be supplied; the oracle run fills it in"
        )
    return problems


def generate_for_program(
    program: str,
    transformed_dir: str,
    out_root: str,
    claude_bin: str,
    min_tests: int,
    timeout: int,
    dry_run: bool = False,
    repo_root: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """Generate test cases for one program; returns ``(count, problems)``."""
    sources = load_program(transformed_dir, program)
    context = build_context(sources.text, program)
    out_dir = os.path.join(out_root, program)
    os.makedirs(out_dir, exist_ok=True)
    prompt = build_prompt(
        context, sources.text, out_dir.replace("\\", "/"), min_tests=min_tests
    )

    if dry_run:
        path = write_prompt(os.path.join(out_dir, "prompt.txt"), prompt)
        return 0, [f"dry run: prompt written to {path}, claude not invoked"]

    # The prompt carries the whole program source and variable table, so it runs
    # to tens of kilobytes.  Passing it as an argv element dies on Windows with
    # WinError 206 (the CreateProcess command line caps at 32767 characters), so
    # it goes in over stdin, which has no such limit.
    cmd = [
        claude_bin, "-p",
        "--permission-mode", "acceptEdits",
        "--add-dir", os.path.abspath(out_dir),
    ]
    proc = subprocess.run(
        cmd, input=prompt, cwd=repo_root or os.getcwd(),
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        return 0, [
            f"claude exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '')[:500]}"
        ]

    produced = sorted(
        q for q in glob.glob(os.path.join(out_dir, "*.json"))
        if not os.path.basename(q).startswith("coverage_manifest")
    )
    problems: List[str] = []
    if len(produced) < min_tests:
        problems.append(
            f"only {len(produced)} test case(s) written, {min_tests} required"
        )
    for path in produced:
        try:
            testcase = TestCase.load(path)
        except (ValueError, KeyError) as exc:
            problems.append(f"{os.path.basename(path)}: not valid test JSON ({exc})")
            continue
        if testcase.expected_values is not None:
            # A model (or a hand-authored session-limit fallback case) must
            # never ship expected_values -- stage 3's oracle run is the only
            # legitimate source.  Reporting this as a warning string is not
            # enough on its own: left in the file, oracle_runner's is_frozen
            # check would treat the case as already blessed and skip it,
            # letting an unverified value silently become "ground truth" for
            # every later stage.  Strip it and rewrite the file so a real
            # oracle run is still required before this case can be used.
            problems.append(
                f"{os.path.basename(path)}: expected_values must not be supplied; "
                "stripped so the oracle run (stage 3) fills it in for real"
            )
            testcase.expected_values = None
            testcase.write(path)
        for problem in validate_testcase(testcase, sources):
            problems.append(f"{os.path.basename(path)}: {problem}")
    return len(produced), problems


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.testgen.generate_testcases",
        description="generate test cases for transformed programs with claude",
    )
    p.add_argument("transformed_dir", help="directory of transformed .cbl programs")
    p.add_argument("--out", default="testsuites")
    p.add_argument("--claude-bin", default="claude")
    p.add_argument("--program", action="append", default=[],
                   help="limit to this program (repeatable)")
    p.add_argument("--min-tests", type=int, default=DEFAULT_MIN_TESTS,
                   help="test cases required per program "
                        f"(default {DEFAULT_MIN_TESTS})")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--force", action="store_true",
                   help="regenerate even when test cases already exist")
    p.add_argument("--dry-run", action="store_true",
                   help="write the prompt for inspection without calling claude")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    programs = args.program or sorted(
        os.path.splitext(os.path.basename(q))[0]
        for q in glob.glob(os.path.join(args.transformed_dir, "*.cbl"))
    )
    if not programs:
        sys.stderr.write(f"error: no .cbl files in {args.transformed_dir}\n")
        return 2

    failures = 0
    for program in programs:
        out_dir = os.path.join(args.out, program)
        existing = [
            q for q in glob.glob(os.path.join(out_dir, "*.json"))
            if not os.path.basename(q).startswith("coverage_manifest")
        ]
        if existing and not args.force:
            if not args.quiet:
                print(f"{program}: {len(existing)} test case(s) already present, "
                      "skipping (use --force to regenerate)")
            continue
        try:
            count, problems = generate_for_program(
                program, args.transformed_dir, args.out, args.claude_bin,
                args.min_tests, args.timeout, args.dry_run,
            )
        except (FileNotFoundError, TransformError) as exc:
            sys.stderr.write(f"{program}: {exc}\n")
            failures += 1
            continue
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"{program}: claude timed out after {args.timeout}s\n")
            failures += 1
            continue
        if not args.quiet:
            print(f"{program}: {count} test case(s) generated")
        for problem in problems:
            sys.stderr.write(f"{program}: {problem}\n")
        if problems and not args.dry_run:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
