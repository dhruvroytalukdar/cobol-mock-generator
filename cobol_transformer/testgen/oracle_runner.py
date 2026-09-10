"""Freeze real expected values into a test case by executing the program.

This is the step that makes the whole scheme honest.  Nothing upstream is
allowed to predict what a variable will hold at the end of a run: a model
choosing inputs cannot trace mocked CICS/SQL substitution by hand, and a
plausible-looking guess would bake a wrong assertion into a suite that then
"passes".  So the expected values come from one place only -- a real GnuCOBOL
execution of the program under the chosen inputs, read back off its stdout.

Because the transformed program is deterministic (no argv, no stdin, seed-free
mocks), that observed value is reproducible, which is exactly what makes it
usable as a golden.

A test case whose oracle could not compile or run is never left half-blessed:
it keeps no ``expected_values`` and the command exits non-zero.

    python -m cobol_transformer.testgen.oracle_runner testsuites/lgtestp1 \
        [--transformed-dir transformed] [--force] [--keep-going]
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..errors import TransformError
from ..gnucobol.gnucobol_runner import CompileResult, GnuCobolRunner
from .cfg import ProgramSources, load_program
from .instrumenter import TestCase, instrument

DUMP_LINE = re.compile(r"^TC:DUMP:(?P<var>[^=]+)=(?P<val>.*)$")


def parse_dump(stdout: str) -> Dict[str, str]:
    """Extract ``TC:DUMP:`` values, last occurrence winning.

    Last-wins matters: a program that both falls through to the trailer and
    reaches an explicit exit would report twice, and the final observation is
    the one that describes the end of the run.
    """
    out: Dict[str, str] = {}
    for line in stdout.splitlines():
        m = DUMP_LINE.match(line.rstrip("\r"))
        if m:
            out[m.group("var").strip()] = m.group("val").rstrip()
    return out


def _binary_path(source: str, runner: GnuCobolRunner) -> str:
    base = os.path.splitext(source)[0]
    if os.name == "nt" and not runner.use_wsl:
        return base + ".exe"
    return base


def build_and_run(
    source_path: str, runner: GnuCobolRunner, timeout: int = 60,
    extra_flags: Optional[List[str]] = None,
) -> Tuple[CompileResult, Optional[CompileResult]]:
    """Compile ``source_path`` and, if that worked, run it."""
    binary = _binary_path(source_path, runner)
    compiled = runner.compile(source_path, binary, extra_flags=extra_flags)
    if not compiled.ok:
        return compiled, None
    return compiled, runner.run(binary, timeout=timeout)


def bless(
    testcase: TestCase,
    sources: ProgramSources,
    out_dir: str,
    runner: GnuCobolRunner,
    timeout: int = 60,
    extra_flags: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Run ``testcase``'s oracle and write its expected values back."""
    result = instrument(sources.text, testcase, sources.symbols, mode="oracle")
    source_path = os.path.join(out_dir, f"{testcase.test_id}.cbl")
    result.write(source_path)

    compiled, ran = build_and_run(source_path, runner, timeout, extra_flags)
    if not compiled.ok:
        return False, f"compile failed (exit {compiled.returncode}):\n" + (
            compiled.stderr or compiled.stdout
        )[:2000]
    assert ran is not None
    # A negative code means the process never exited on its own -- the runner
    # timed out -- which is the only exit condition that is unambiguously a
    # failure.  A *non-zero* code is not: RETURN-CODE is ordinary program state
    # in this corpus, and a transformed program can leave it holding anything
    # (one leaves it as four spaces, exiting 32) while running perfectly and
    # emitting every dump line.  What proves the oracle worked is the dump.
    if ran.returncode < 0:
        return False, f"run did not complete: {(ran.stderr or ran.stdout)[:2000]}"

    observed = parse_dump(ran.stdout)
    missing = [n for n in testcase.variables_to_check if n not in observed]
    if missing:
        return False, (
            f"the oracle run (exit {ran.returncode}) produced no value for: "
            + ", ".join(missing)
            + " -- the program may exit on a path that skips the dump"
        )

    testcase.expected_values = {n: observed[n] for n in testcase.variables_to_check}
    testcase.generated_at = testcase.generated_at or datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    testcase.generated_by = "claude+oracle" if testcase.generated_by else "oracle"
    testcase.oracle_source = os.path.relpath(source_path).replace("\\", "/")
    testcase.write()
    return True, ", ".join(f"{k}={v!r}" for k, v in testcase.expected_values.items())


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="cobol_transformer.testgen.oracle_runner",
        description="execute test cases to freeze their expected values",
    )
    p.add_argument("test_dir", help="testsuites/<program> directory")
    p.add_argument("--transformed-dir", default="transformed")
    p.add_argument("--instrumented-dir", default="instrumented")
    p.add_argument("--program", help="defaults to the test directory's name")
    p.add_argument("--force", action="store_true",
                   help="re-bless test cases that already have expected values")
    p.add_argument("--keep-going", action="store_true",
                   help="continue after a test case fails to bless")
    p.add_argument("--run-timeout", type=int, default=60)
    p.add_argument("--gnucobol-flags", default="")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    program = args.program or os.path.basename(os.path.normpath(args.test_dir))
    try:
        sources = load_program(args.transformed_dir, program)
    except (FileNotFoundError, TransformError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    paths = sorted(glob.glob(os.path.join(args.test_dir, "*.json")))
    paths = [q for q in paths if not os.path.basename(q).startswith("coverage_manifest")]
    if not paths:
        sys.stderr.write(f"error: no test cases in {args.test_dir}\n")
        return 2

    out_dir = os.path.join(args.instrumented_dir, program, "oracle")
    runner = GnuCobolRunner()
    flags = args.gnucobol_flags.split() or None
    failures = 0
    blessed = 0

    for path in paths:
        testcase = TestCase.load(path)
        if testcase.is_frozen and not args.force:
            if not args.quiet:
                print(f"{testcase.test_id}: already frozen, skipping")
            continue
        try:
            ok, detail = bless(
                testcase, sources, out_dir, runner, args.run_timeout, flags
            )
        except TransformError as exc:
            ok, detail = False, str(exc)
        if ok:
            blessed += 1
            if not args.quiet:
                print(f"{testcase.test_id}: frozen  {detail}")
        else:
            failures += 1
            sys.stderr.write(f"{testcase.test_id}: FAILED - {detail}\n")
            if not args.keep_going:
                return 1

    if not args.quiet:
        print(f"{program}: {blessed} frozen, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
