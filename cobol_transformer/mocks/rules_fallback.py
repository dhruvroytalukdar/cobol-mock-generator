"""The rule that always matches, so no construct is ever left untranslated.

Reaching this rule for a verb that has a specific implementation is a coverage
gap, and it is reported as ``W-FALLBACK-RULE-USED`` rather than passing
silently.  The behaviour it emits -- a trace plus success status codes -- is
safe to generate with no semantic understanding of the command at all.
"""
from __future__ import annotations

import re
from typing import List

from ..analysis.exec_text_parser import split_arg_identifier
from ..errors import Diagnostic, Severity
from .codegen import cobol_string_literal
from .rule_engine import MockResult, MockRule, RuleContext
from .rules_cics import TRACE_PREFIX

_RESP_OPTION = re.compile(r"\b(RESP2?|SQLCODE)\s*\(\s*([A-Za-z0-9$#@_-]+)\s*\)",
                          re.IGNORECASE)


class GenericFallbackRule(MockRule):
    name = "generic_fallback"

    def matches(self, ctx: RuleContext) -> bool:
        return True

    def generate(self, ctx: RuleContext) -> MockResult:
        # A declarative construct must not produce procedural statements.
        if ctx.declarative:
            return MockResult(
                statements=[],
                confidence="fallback",
                diagnostics=[
                    Diagnostic(
                        code="W-FALLBACK-RULE-USED",
                        message=(
                            f"no specific rule for declarative "
                            f"{ctx.category.value} {ctx.verb!r}; commented out only"
                        ),
                        severity=Severity.INFO,
                    )
                ],
            )

        verb = ctx.verb or "EXEC"
        out: List[str] = [
            f"DISPLAY {cobol_string_literal(f'{TRACE_PREFIX} {verb} @{ctx.paragraph} (generic)')}"
        ]

        # Zero any status field the raw text names, so the success path holds.
        raw = ctx.command.raw if ctx.command else ctx.range.source_text
        seen = set()
        for m in _RESP_OPTION.finditer(raw):
            ident = m.group(2)
            if ident.upper() in seen:
                continue
            seen.add(ident.upper())
            if ident in ctx.symbols:
                out.append(f"MOVE 0 TO {ident}")
        if ctx.category.value == "sql" and "SQLCODE" in ctx.symbols:
            out.append("MOVE 0 TO SQLCODE")

        return MockResult(
            statements=out,
            confidence="fallback",
            diagnostics=[
                Diagnostic(
                    code="W-FALLBACK-RULE-USED",
                    message=f"no specific rule matched {ctx.category.value} {verb!r}",
                    severity=Severity.WARNING,
                )
            ],
        )
