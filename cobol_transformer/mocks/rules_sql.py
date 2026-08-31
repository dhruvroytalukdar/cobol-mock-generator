"""Per-verb mocks for embedded ``EXEC SQL``.

``SQLCODE`` is never synthesised: ``EXEC SQL INCLUDE SQLCA`` is expanded by the
inliner into ordinary WORKING-STORAGE, so the mocks simply move into the field
that is already there.

The one place a mock must actively steer control flow is ``FETCH``.  Cursor
loops are written as ``PERFORM ... UNTIL SQLCODE = 100``; a mock that always
reported success would spin forever.  Each cursor therefore has a row budget:
rows are returned until it is exhausted, then ``SQLCODE`` becomes 100 so the
loop ends exactly the way a real short result set would end it.
"""
from __future__ import annotations

from typing import List, Optional

from ..analysis.node_classifier import Category
from .codegen import cobol_string_literal
from .dummy_values import literal_for
from .rule_engine import MockResult, MockRule, RuleContext
from .rules_cics import trace

SQLCODE_OK = 0
SQLCODE_NOT_FOUND = 100
DEFAULT_ROWS_PER_CURSOR = 1


def _set_sqlcode(ctx: RuleContext, value: int, out: List[str]) -> None:
    """Move a status into SQLCODE when the field exists."""
    if "SQLCODE" in ctx.symbols:
        out.append(f"MOVE {value} TO SQLCODE")


def _populate_host_vars(ctx: RuleContext, names: List[str], out: List[str]) -> None:
    for raw in names:
        name = raw.split(".")[-1]
        sym = ctx.symbols.get(name)
        if sym is None:
            continue
        lit = literal_for(sym, ctx.values)
        if lit is not None:
            out.append(f"MOVE {lit} TO {sym.name}")


def _into_list(ctx: RuleContext) -> List[str]:
    raw = (ctx.command.options.get("_INTO") or "") if ctx.command else ""
    return [x for x in raw.split(",") if x]


class _SqlRule(MockRule):
    verbs: tuple = ()

    def matches(self, ctx: RuleContext) -> bool:
        return (
            ctx.category is Category.SQL
            and ctx.command is not None
            and ctx.verb in self.verbs
        )


class SqlDeclarativeRule(_SqlRule):
    """``DECLARE CURSOR``/``DECLARE TABLE`` -- declarations, not statements.

    These appear in the DATA DIVISION, where a procedural statement would not
    compile, so they are commented out and nothing is emitted in their place.
    """

    name = "sql_declarative"
    verbs = ("DECLARE CURSOR", "DECLARE TABLE", "DECLARE", "BEGIN", "END",
             "INCLUDE", "WHENEVER")

    def generate(self, ctx: RuleContext) -> MockResult:
        if ctx.declarative:
            return MockResult(statements=[])
        return MockResult(statements=[trace(ctx)])


class SqlSelectRule(_SqlRule):
    """Single-row ``SELECT``: fill the INTO list, report success."""

    name = "sql_select"
    verbs = ("SELECT",)

    def generate(self, ctx: RuleContext) -> MockResult:
        table = (ctx.command.options.get("_TABLE") or "?") if ctx.command else "?"
        out = [trace(ctx, cobol_string_literal(f"TABLE={table}"))]
        _populate_host_vars(ctx, _into_list(ctx), out)
        _set_sqlcode(ctx, SQLCODE_OK, out)
        return MockResult(statements=out)


class SqlFetchRule(_SqlRule):
    """``FETCH``: return a bounded number of rows, then signal end of data."""

    name = "sql_fetch"
    verbs = ("FETCH",)

    def generate(self, ctx: RuleContext) -> MockResult:
        cursor = (ctx.command.options.get("CURSOR") or "CURSOR").upper()
        budget = max(
            int(ctx.config.get("rows_per_cursor", DEFAULT_ROWS_PER_CURSOR)), 1
        )
        out = [trace(ctx, cobol_string_literal(cursor))]

        if "SQLCODE" not in ctx.symbols:
            return MockResult(statements=out)

        # The count has to happen at run time: one FETCH statement is executed
        # repeatedly by its loop, so a transform-time counter could never end
        # it.  A per-site counter reports end-of-data once the budget is spent,
        # which is what satisfies PERFORM UNTIL SQLCODE = 100.
        counter = ctx.allocate_counter("MOCK-FETCH-CNT")
        rows: List[str] = []
        _populate_host_vars(ctx, _into_list(ctx), rows)

        out.append(f"ADD 1 TO {counter}")
        out.append(
            f"IF {counter} > {budget} "
            f"MOVE {SQLCODE_NOT_FOUND} TO SQLCODE "
            "ELSE "
            f"MOVE {SQLCODE_OK} TO SQLCODE "
            + " ".join(rows)
            + " END-IF"
        )
        return MockResult(statements=out)


class SqlCursorLifecycleRule(_SqlRule):
    """``OPEN``/``CLOSE`` have no observable effect on program data."""

    name = "sql_cursor_lifecycle"
    verbs = ("OPEN", "CLOSE")

    def generate(self, ctx: RuleContext) -> MockResult:
        cursor = (ctx.command.options.get("CURSOR") or "") if ctx.command else ""
        out = [trace(ctx, cobol_string_literal(cursor)) if cursor else trace(ctx)]
        if ctx.verb == "OPEN":
            # Re-opening a cursor restarts its result set.
            ctx.cursor_state[cursor.upper()] = 0
        _set_sqlcode(ctx, SQLCODE_OK, out)
        return MockResult(statements=out)


class SqlUpdateRule(_SqlRule):
    """``INSERT``/``UPDATE``/``DELETE``: report the change, then succeed."""

    name = "sql_update"
    verbs = ("INSERT", "UPDATE", "DELETE")

    def generate(self, ctx: RuleContext) -> MockResult:
        table = (ctx.command.options.get("_TABLE") or "?") if ctx.command else "?"
        out = [trace(ctx, cobol_string_literal(f"TABLE={table}"))]
        _set_sqlcode(ctx, SQLCODE_OK, out)
        return MockResult(statements=out)


class SqlSetRule(_SqlRule):
    """``SET :hv = <special register>`` -- give the target a defined value."""

    name = "sql_set"
    verbs = ("SET",)

    def generate(self, ctx: RuleContext) -> MockResult:
        out = [trace(ctx)]
        names = [x for x in (ctx.command.options.get("_HOSTVARS") or "").split(",") if x]
        _populate_host_vars(ctx, names[:1], out)
        _set_sqlcode(ctx, SQLCODE_OK, out)
        return MockResult(statements=out)


SQL_RULES = [
    SqlDeclarativeRule(),
    SqlSelectRule(),
    SqlFetchRule(),
    SqlCursorLifecycleRule(),
    SqlUpdateRule(),
    SqlSetRule(),
]
