"""Command-line entry point.

Subcommands mirror the pipeline stages so a run can be stopped and inspected at
any point::

    inline     copybook expansion only
    detect     expansion + detection, printed as a table, nothing written
    transform  full pipeline, writes .cbl + manifest + report
    build      transform, then compile (and optionally run) with GnuCOBOL
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .analysis.node_classifier import Category
from .discovery.copybook_resolver import CopybookResolver
from .errors import TransformError
from .inline.inliner import Inliner
from .linetools import LineIndex
from .pipeline import PipelineOptions, run
from .verify import verify
from .gnucobol.gnucobol_runner import GnuCobolRunner
from .output.writer import write_outputs


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="COBOL program to process")
    parser.add_argument(
        "--copybooks", action="append", default=[], metavar="DIR",
        help="copybook search directory (repeatable)",
    )
    parser.add_argument(
        "--continue-on-missing-copybook", action="store_true", default=False,
        help="emit a placeholder instead of failing when a copybook is absent",
    )
    parser.add_argument("--no-ast", action="store_true",
                        help="skip the AST backend and use the lexical detector")
    parser.add_argument("--ast-url", default="http://127.0.0.1:4010")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--rows-per-cursor", type=int, default=1,
                        help="rows a mocked cursor returns before SQLCODE 100")
    parser.add_argument("--quiet", action="store_true")


def _options(args: argparse.Namespace) -> PipelineOptions:
    return PipelineOptions(
        copybook_dirs=args.copybooks,
        continue_on_missing_copybook=args.continue_on_missing_copybook,
        use_ast=not args.no_ast,
        ast_url=args.ast_url,
        seed=args.seed,
        rows_per_cursor=args.rows_per_cursor,
    )


def cmd_inline(args: argparse.Namespace) -> int:
    source_dir = os.path.dirname(os.path.abspath(args.source))
    resolver = CopybookResolver(args.copybooks, source_dir=source_dir)
    inliner = Inliner(resolver, continue_on_missing=args.continue_on_missing_copybook)
    result = inliner.inline_file(args.source)
    out = args.output or os.path.splitext(args.source)[0] + ".expanded.cbl"
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(result.text)
    if not args.quiet:
        print(f"expanded -> {out}  ({len(result.text.splitlines())} lines)")
        for name, count in sorted(result.copybooks_used.items()):
            print(f"  copybook {name} x{count}")
        for d in result.diagnostics:
            print(f"  {d}")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    result = run(args.source, _options(args))
    index = LineIndex(result.expanded_text)
    print(f"{'LINE':>6}  {'CAT':<6} {'VERB':<16} {'RULE':<22} {'PERIOD':<6} STATUS")
    print("-" * 92)
    for c in result.manifest.constructs:
        print(
            f"{c.expanded_line_start:>6}  {c.category:<6} {c.verb[:16]:<16} "
            f"{c.matched_rule[:22]:<22} {str(c.had_trailing_period):<6} {c.status}"
        )
    s = result.manifest.to_dict()["summary"]
    print("-" * 92)
    print(f"backend={result.manifest.detection_backend}  "
          f"constructs={s['constructs']}  fallback={s['fallback_rules_used']}  "
          f"skipped={s['skipped']}")
    for d in result.diagnostics:
        if d.severity.value != "INFO":
            print(f"  {d}")
    return 0


def cmd_transform(args: argparse.Namespace) -> int:
    result = run(args.source, _options(args))
    paths = write_outputs(
        result,
        output=args.output,
        manifest_path=args.manifest,
        report_path=args.report,
        expanded_path=args.save_expanded,
    )
    if not args.quiet:
        s = result.manifest.to_dict()["summary"]
        print(f"transformed -> {paths['output']}")
        print(f"  backend={result.manifest.detection_backend} "
              f"constructs={s['constructs']} fallback={s['fallback_rules_used']} "
              f"skipped={s['skipped']}")
        if result.manifest.synthesized_fields:
            print(f"  synthesized EIB fields: "
                  f"{', '.join(result.manifest.synthesized_fields)}")
    return 1 if result.manifest.skipped_count else 0


def cmd_build(args: argparse.Namespace) -> int:
    result = run(args.source, _options(args))
    paths = write_outputs(
        result,
        output=args.output,
        manifest_path=args.manifest,
        report_path=args.report,
        expanded_path=args.save_expanded,
    )
    runner = GnuCobolRunner()
    binary = os.path.splitext(paths["output"])[0]
    if os.name == "nt":
        binary += ".exe" if not runner.use_wsl else ""
    comp = runner.compile(paths["output"], binary, extra_flags=args.gnucobol_flags.split() if args.gnucobol_flags else None)
    result.manifest.compile_result = comp.to_dict()

    if not args.quiet:
        print(f"transformed -> {paths['output']}")
        print(f"compile: {'OK' if comp.ok else 'FAILED'} (exit {comp.returncode})")
    if not comp.ok:
        sys.stderr.write(comp.stderr or comp.stdout)
        write_outputs(result, output=None, manifest_path=paths["manifest"],
                      report_path=paths["report"])
        return 2

    if args.run:
        res = runner.run(binary, timeout=args.run_timeout)
        result.manifest.compile_result["run"] = res.to_dict()
        if not args.quiet:
            print(f"run: exit {res.returncode}")
            print(res.stdout[:4000])
            if res.stderr:
                sys.stderr.write(res.stderr[:2000])
    write_outputs(result, output=None, manifest_path=paths["manifest"],
                  report_path=paths["report"])
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Prove that nothing but the mocked constructs changed."""
    result = run(args.source, _options(args))
    v = verify(result.expanded_text, result.output_text, result.manifest)
    if v.ok:
        if not args.quiet:
            print(f"{os.path.basename(args.source)}: VERIFIED - "
                  f"{v.expected_lines} lines reconstruct exactly; "
                  f"{len(result.manifest.constructs)} mocked constructs")
        return 0
    print(f"{os.path.basename(args.source)}: {len(v.differences)} unexpected "
          f"difference(s)", file=sys.stderr)
    for d in v.differences:
        print("  " + d.replace("\n", "\n  "), file=sys.stderr)
    return 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cobol_transformer",
        description="Transform mainframe COBOL into self-contained GnuCOBOL programs",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("inline", help="expand copybooks only")
    _common(pi)
    pi.add_argument("-o", "--output")
    pi.set_defaults(func=cmd_inline)

    pd = sub.add_parser("detect", help="list constructs that would be mocked")
    _common(pd)
    pd.set_defaults(func=cmd_detect)

    pt = sub.add_parser("transform", help="full transformation")
    _common(pt)
    pt.add_argument("-o", "--output")
    pt.add_argument("--manifest")
    pt.add_argument("--report")
    pt.add_argument("--save-expanded")
    pt.set_defaults(func=cmd_transform)

    pb = sub.add_parser("build", help="transform then compile with GnuCOBOL")
    _common(pb)
    pb.add_argument("-o", "--output")
    pb.add_argument("--manifest")
    pb.add_argument("--report")
    pb.add_argument("--save-expanded")
    pb.add_argument("--run", action="store_true", help="run the compiled program")
    pb.add_argument("--run-timeout", type=int, default=60)
    pb.add_argument("--gnucobol-flags", default="")
    pb.set_defaults(func=cmd_build)

    pv = sub.add_parser(
        "verify",
        help="reverse the transformation and confirm only mocks changed",
    )
    _common(pv)
    pv.set_defaults(func=cmd_verify)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except TransformError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
