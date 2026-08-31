"""Write the transformed program and its diagnostic artefacts."""
from __future__ import annotations

import os
from typing import Dict, Optional

from ..pipeline import PipelineResult


def _default(path: str, suffix: str) -> str:
    stem = os.path.splitext(path)[0]
    return stem + suffix


def render_report(result: PipelineResult) -> str:
    """Human-readable summary, grouped by paragraph."""
    m = result.manifest
    lines = [
        "=" * 78,
        f"COBOL transformation report - {m.program}",
        "=" * 78,
        f"source            : {m.source_path}",
        f"output            : {m.output_path}",
        f"detection backend : {m.detection_backend}",
    ]
    if m.ast_error:
        lines.append(f"ast fallback cause: {m.ast_error.splitlines()[0][:110]}")
    lines.append(f"linkage promoted  : {m.linkage_promoted}")
    if m.synthesized_fields:
        lines.append(f"synthesized EIB   : {', '.join(m.synthesized_fields)}")
    if m.copybooks:
        lines.append("copybooks:")
        for name, info in sorted(m.copybooks.items()):
            tag = " (generated)" if info.get("synthesized") else ""
            lines.append(f"    {name} x{info['occurrences']}{tag}")

    summary = m.to_dict()["summary"]
    lines += [
        "",
        f"constructs        : {summary['constructs']}",
        f"by status         : {summary['by_status']}",
        f"fallback rule use : {summary['fallback_rules_used']}",
        f"skipped           : {summary['skipped']}",
        "",
        "-" * 78,
        f"{'LINE':>6}  {'CAT':<6} {'VERB':<16} {'RULE':<22} {'P':<2} STATUS",
        "-" * 78,
    ]
    for c in m.constructs:
        lines.append(
            f"{c.expanded_line_start:>6}  {c.category:<6} {c.verb[:16]:<16} "
            f"{c.matched_rule[:22]:<22} {'Y' if c.had_trailing_period else 'n':<2} "
            f"{c.status}"
        )

    problems = [d for d in m.diagnostics if d.get("severity") != "INFO"]
    if problems:
        lines += ["", "-" * 78, "diagnostics:", "-" * 78]
        for d in problems:
            loc = f" line {d['line']}" if d.get("line") else ""
            lines.append(f"  [{d['severity']}] {d['code']}{loc}: {d['message'][:150]}")

    if m.compile_result:
        lines += ["", "-" * 78, "compile:", "-" * 78]
        lines.append(f"  ok={m.compile_result.get('ok')} "
                     f"exit={m.compile_result.get('returncode')}")
        err = (m.compile_result.get("stderr") or "").strip()
        if err:
            lines += ["  " + l for l in err.splitlines()[:40]]
    return "\n".join(lines) + "\n"


def write_outputs(
    result: PipelineResult,
    output: Optional[str] = None,
    manifest_path: Optional[str] = None,
    report_path: Optional[str] = None,
    expanded_path: Optional[str] = None,
) -> Dict[str, str]:
    """Write the artefacts; ``output=None`` refreshes manifest/report only."""
    src = result.manifest.source_path
    paths: Dict[str, str] = {}

    if output is not False and output is not None or output is None:
        out = output or _default(src, ".transformed.cbl")
        if output is not None or not result.manifest.output_path:
            result.manifest.output_path = os.path.abspath(out)
        paths["output"] = result.manifest.output_path
        if output is not None or not os.path.exists(paths["output"]):
            os.makedirs(os.path.dirname(paths["output"]) or ".", exist_ok=True)
            with open(paths["output"], "w", encoding="utf-8", newline="\n") as fh:
                fh.write(result.output_text)

    if expanded_path:
        with open(expanded_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(result.expanded_text)
        paths["expanded"] = expanded_path

    mpath = manifest_path or _default(paths.get("output", src), ".manifest.json")
    with open(mpath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(result.manifest.to_json())
    paths["manifest"] = mpath

    rpath = report_path or _default(paths.get("output", src), ".report.txt")
    with open(rpath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_report(result))
    paths["report"] = rpath
    return paths
