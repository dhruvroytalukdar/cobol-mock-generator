"""Per-verb mocks for ``EXEC CICS`` commands.

Flow preservation is the governing constraint.  A CICS command either returns
control to the next statement or it does not, and the mock must do the same:

* ``RETURN`` hands control back to CICS -- the program ends.  Its mock is
  ``GOBACK``, not a trace line, because a trace line would let execution fall
  into code that originally never ran.
* ``ABEND`` terminates abnormally; its mock also ends the program.
* every other verb in this corpus returns to the following statement, so its
  mock is a trace plus whatever data population the real command would have
  done, and execution continues exactly as before.

Fields named by ``RESP``/``RESP2`` are set to zero (success) using a numeric
literal -- never ``DFHRESP(NORMAL)``, which is itself untranslatable.
"""
from __future__ import annotations

from typing import List, Optional

from ..analysis.exec_text_parser import literal_of, split_arg_identifier
from ..analysis.node_classifier import Category
from .codegen import cobol_string_literal
from .dummy_values import literal_for
from .rule_engine import MockResult, MockRule, RuleContext

TRACE_PREFIX = ">>> MOCK"

# CICS condition values used when a mocked resource reports end-of-data.
ITEMERR = 26
ENDFILE = 20


def trace(ctx: RuleContext, detail: str = "") -> str:
    """A greppable trace line naming the verb and its paragraph."""
    label = f"{TRACE_PREFIX} {ctx.verb} @{ctx.paragraph}"
    if detail:
        return f"DISPLAY {cobol_string_literal(label + ': ')} {detail}"
    return f"DISPLAY {cobol_string_literal(label)}"


def _display_operand(ctx: RuleContext, arg: Optional[str]) -> Optional[str]:
    """Render an option argument as something DISPLAY can take."""
    if not arg:
        return None
    lit = literal_of(arg)
    if lit is not None:
        return cobol_string_literal(lit)
    ident = split_arg_identifier(arg)
    if ident and ident in ctx.symbols:
        return ident
    return None


def set_resp(ctx: RuleContext, out: List[str], value: int = 0) -> None:
    """Set every RESP/RESP2 field the command names (0 = NORMAL by default)."""
    for opt in ("RESP", "RESP2"):
        arg = ctx.command.option(opt) if ctx.command else None
        ident = split_arg_identifier(arg or "")
        if ident and ident in ctx.symbols:
            out.append(f"MOVE {value} TO {ident}")


def bounded_read(
    ctx: RuleContext,
    out: List[str],
    body: List[str],
    exhausted_code: int,
    label: str,
) -> MockResult:
    """Emit a read that succeeds for a few iterations, then reports end-of-data.

    Sequential reads (``READQ TS ... NEXT``, ``READNEXT``, SQL ``FETCH``) sit
    inside loops that end only when the resource runs out.  The generated code
    is static, so the bound cannot be decided while transforming -- the same
    statement executes on every iteration.  A per-site counter in
    WORKING-STORAGE therefore does the counting at *run* time, which is what
    lets the loop terminate the way a short queue or result set would end it.
    """
    budget = max(int(ctx.config.get("rows_per_cursor", 1)), 1)
    counter = ctx.allocate_counter(f"MOCK-{label}-CNT")
    status_moves = _resp_moves(ctx, exhausted_code)
    ok_moves = _resp_moves(ctx, 0)

    out.append(f"ADD 1 TO {counter}")
    inner_ok = "; ".join(ok_moves + body) if (ok_moves or body) else "CONTINUE"
    inner_end = "; ".join(status_moves) if status_moves else "CONTINUE"
    # Rendered as one statement so the wrapper keeps it a single sentence.
    out.append(
        f"IF {counter} > {budget} "
        + " ".join(status_moves)
        + (" " if status_moves else " CONTINUE ")
        + "ELSE "
        + " ".join(ok_moves + body)
        + (" " if (ok_moves or body) else " CONTINUE ")
        + "END-IF"
    )
    return MockResult(statements=out)


def _resp_moves(ctx: RuleContext, value: int) -> List[str]:
    moves: List[str] = []
    for opt in ("RESP", "RESP2"):
        arg = ctx.command.option(opt) if ctx.command else None
        ident = split_arg_identifier(arg or "")
        if ident and ident in ctx.symbols:
            moves.append(f"MOVE {value} TO {ident}")
    return moves


def populate(ctx: RuleContext, target: Optional[str], out: List[str]) -> bool:
    """Fill ``target`` with deterministic values; True when anything was emitted.

    An elementary field is moved into directly.  A group is filled leaf by leaf
    so each field gets a value matching its own PICTURE, and ``REDEFINES``
    siblings are skipped so overlapping storage is written only once.
    """
    ident = split_arg_identifier(target or "")
    if not ident:
        return False
    sym = ctx.symbols.get(ident)
    if sym is None:
        return False

    if sym.pic_text is not None:
        lit = literal_for(sym, ctx.values)
        if lit is None:
            return False
        out.append(f"MOVE {lit} TO {sym.name}")
        return True

    wrote = False
    for leaf in ctx.symbols.elementary_fields(ident):
        lit = literal_for(leaf, ctx.values)
        if lit is None or leaf.is_filler:
            continue
        out.append(f"MOVE {lit} TO {leaf.name}")
        wrote = True
    if not wrote:
        # A group with no usable leaves is still cleared, so the caller sees a
        # defined buffer rather than whatever was there before.
        out.append(f"MOVE SPACES TO {sym.name}")
        wrote = True
    return wrote


class _CicsRule(MockRule):
    """Base: matches CICS commands whose verb is in ``verbs``."""

    verbs: tuple = ()

    def matches(self, ctx: RuleContext) -> bool:
        return (
            ctx.category is Category.CICS
            and ctx.command is not None
            and ctx.verb in self.verbs
        )


class ReturnRule(_CicsRule):
    """``RETURN`` ends the program, so the mock must end it too."""

    name = "cics_return"
    verbs = ("RETURN",)

    def generate(self, ctx: RuleContext) -> MockResult:
        out = [trace(ctx)]
        transid = _display_operand(ctx, ctx.command.option("TRANSID"))
        if transid:
            out[0] = trace(ctx, transid)
        set_resp(ctx, out)
        # GOBACK reproduces "control leaves this program here".  Without it the
        # statements after RETURN would run, which they never did under CICS.
        out.append("GOBACK")
        return MockResult(statements=out)


class AbendRule(_CicsRule):
    """``ABEND`` terminates abnormally; the mock reports and stops."""

    name = "cics_abend"
    verbs = ("ABEND",)

    def generate(self, ctx: RuleContext) -> MockResult:
        code = literal_of(ctx.command.option("ABCODE") or "") or "????"
        out = [
            trace(ctx, cobol_string_literal(f"ABCODE={code}")),
            "GOBACK",
        ]
        return MockResult(statements=out)


class LinkRule(_CicsRule):
    """``LINK`` invokes another program and returns; execution continues."""

    name = "cics_link"
    verbs = ("LINK", "XCTL", "START")

    def generate(self, ctx: RuleContext) -> MockResult:
        prog = ctx.command.option("PROGRAM", "TRANSID")
        label = literal_of(prog or "") or split_arg_identifier(prog or "") or "?"
        out = [trace(ctx, cobol_string_literal(str(label)))]
        set_resp(ctx, out)
        if ctx.verb == "XCTL":
            # XCTL transfers control and never comes back.
            out.append("GOBACK")
        return MockResult(statements=out)


class FileRule(_CicsRule):
    """VSAM file access through CICS."""

    name = "cics_file"
    verbs = ("READ", "WRITE", "REWRITE", "DELETE", "UNLOCK", "STARTBR",
             "READNEXT", "READPREV", "ENDBR")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        fname = literal_of(cmd.option("FILE", "DATASET") or "") or "?"
        key = _display_operand(ctx, cmd.option("RIDFLD"))
        detail = cobol_string_literal(f"FILE={fname}")
        out: List[str] = []

        if ctx.verb in ("READ", "READNEXT", "READPREV"):
            out.append(trace(ctx, detail if key is None else f"{detail} {key}"))
            # A browse read must eventually hit end-of-file so its loop ends.
            if ctx.verb in ("READNEXT", "READPREV"):
                body: List[str] = []
                populate(ctx, cmd.option("INTO"), body)
                return bounded_read(ctx, out, body, ENDFILE, "BROWSE")
            # A real READ fills INTO from the file; the mock fills it with
            # deterministic values so downstream logic has well-defined data.
            populate(ctx, cmd.option("INTO"), out)
        else:
            out.append(trace(ctx, detail if key is None else f"{detail} {key}"))
        set_resp(ctx, out)
        return MockResult(statements=out)


class CounterRule(_CicsRule):
    """Named counter services: report, and supply a deterministic value."""

    name = "cics_counter"
    verbs = ("GET COUNTER", "DEFINE COUNTER", "DELETE COUNTER",
             "QUERY COUNTER", "UPDATE COUNTER")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        counter = _display_operand(ctx, cmd.option("COUNTER", "DCOUNTER"))
        out = [trace(ctx, counter) if counter else trace(ctx)]
        for opt in ("VALUE", "INCREMENT"):
            ident = split_arg_identifier(cmd.option(opt) or "")
            sym = ctx.symbols.get(ident) if ident else None
            if sym is not None and sym.pic.is_numeric:
                out.append(f"MOVE {ctx.values.generated_numeric} TO {ident}")
        set_resp(ctx, out)
        return MockResult(statements=out)


class QueueRule(_CicsRule):
    """Temporary/transient data queues."""

    name = "cics_queue"
    verbs = ("WRITEQ TS", "WRITEQ TD", "READQ TS", "READQ TD",
             "DELETEQ TS", "DELETEQ TD")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        qname = cmd.option("QUEUE", "QNAME", "TDQUEUE") or "?"
        q = _display_operand(ctx, qname)
        out = [trace(ctx, q) if q else trace(ctx)]

        if ctx.verb.startswith("READQ"):
            # A NEXT (or item-less) read walks the queue and must eventually
            # report ITEMERR, or any enclosing browse loop never ends.
            sequential = cmd.has_flag("NEXT") or cmd.option("ITEM") is None
            if sequential:
                body: List[str] = []
                populate(ctx, cmd.option("INTO"), body)
                return bounded_read(ctx, out, body, ITEMERR, "READQ")
            populate(ctx, cmd.option("INTO"), out)
        elif ctx.verb.startswith("WRITEQ"):
            src = _display_operand(ctx, cmd.option("FROM"))
            if src:
                out.append(f"DISPLAY {cobol_string_literal('    DATA: ')} {src}")
        set_resp(ctx, out)
        return MockResult(statements=out)


class TerminalRule(_CicsRule):
    """Screen and terminal I/O."""

    name = "cics_terminal"
    verbs = ("SEND", "SEND MAP", "SEND TEXT", "SEND CONTROL", "SEND PAGE",
             "RECEIVE", "RECEIVE MAP")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        target = _display_operand(ctx, cmd.option("MAP", "MAPSET"))
        out = [trace(ctx, target) if target else trace(ctx)]

        if ctx.verb in ("RECEIVE", "RECEIVE MAP"):
            # Supply input data so the logic that reads the map has values.
            if not populate(ctx, cmd.option("INTO"), out):
                populate(ctx, cmd.option("SET"), out)
        else:
            src = _display_operand(ctx, cmd.option("FROM"))
            if src:
                out.append(f"DISPLAY {cobol_string_literal('    DATA: ')} {src}")
        set_resp(ctx, out)
        return MockResult(statements=out)


class TimeRule(_CicsRule):
    """``ASKTIME``/``FORMATTIME`` produce fixed, deterministic values."""

    name = "cics_time"
    verbs = ("ASKTIME", "FORMATTIME")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        out: List[str] = [trace(ctx)]
        for opt, value in (
            ("ABSTIME", None),
            ("DATESEP", None),
            ("YYYYMMDD", "'20240101'"),
            ("MMDDYYYY", "'01012024'"),
            ("DDMMYYYY", "'01012024'"),
            ("YYYYDDD", "'2024001'"),
            ("DATE", "'20240101'"),
            ("TIME", "'120000'"),
            ("DATESTRING", None),
        ):
            arg = cmd.option(opt)
            ident = split_arg_identifier(arg or "")
            if not ident or ident not in ctx.symbols:
                continue
            sym = ctx.symbols.get(ident)
            if opt == "ABSTIME":
                if sym.pic.is_numeric:
                    out.append(f"MOVE 0 TO {ident}")
                continue
            if value is None:
                continue
            if sym.pic.is_numeric:
                out.append(f"MOVE {value.strip(chr(39))} TO {ident}")
            else:
                out.append(f"MOVE {value} TO {ident}")
        set_resp(ctx, out)
        return MockResult(statements=out)


class AssignRule(_CicsRule):
    """``ASSIGN`` copies system values into program fields."""

    name = "cics_assign"
    verbs = ("ASSIGN",)

    def generate(self, ctx: RuleContext) -> MockResult:
        out: List[str] = [trace(ctx)]
        for opt, arg in (ctx.command.options or {}).items():
            if opt in ("RESP", "RESP2"):
                continue
            ident = split_arg_identifier(arg)
            sym = ctx.symbols.get(ident) if ident else None
            if sym is None:
                continue
            lit = literal_for(sym, ctx.values)
            if lit is not None:
                out.append(f"MOVE {lit} TO {ident}")
        set_resp(ctx, out)
        return MockResult(statements=out)


class NoOpRule(_CicsRule):
    """Verbs with no observable effect once every resource is mocked.

    ``HANDLE CONDITION``/``HANDLE AID`` register branch targets for conditions
    that the mocks never raise, so registering nothing preserves the success
    path exactly.  ``SYNCPOINT``, ``ENQ``/``DEQ`` and the container verbs
    likewise have no effect on program-visible data here.
    """

    name = "cics_noop"
    verbs = ("SYNCPOINT", "ENQ", "DEQ", "HANDLE CONDITION", "HANDLE AID",
             "HANDLE ABEND", "IGNORE CONDITION", "PUSH", "POP", "FREEMAIN",
             "WAIT", "SUSPEND", "DELAY")

    def generate(self, ctx: RuleContext) -> MockResult:
        out = [trace(ctx)]
        set_resp(ctx, out)
        return MockResult(statements=out)


class ContainerRule(_CicsRule):
    """Channel/container access."""

    name = "cics_container"
    verbs = ("GET CONTAINER", "PUT CONTAINER", "DELETE CONTAINER")

    def generate(self, ctx: RuleContext) -> MockResult:
        cmd = ctx.command
        cname = _display_operand(ctx, cmd.option("CONTAINER"))
        out = [trace(ctx, cname) if cname else trace(ctx)]
        if ctx.verb == "GET CONTAINER":
            populate(ctx, cmd.option("INTO"), out)
        set_resp(ctx, out)
        return MockResult(statements=out)


class GetmainRule(_CicsRule):
    """``GETMAIN`` acquires storage; addressability is left untouched."""

    name = "cics_getmain"
    verbs = ("GETMAIN",)

    def generate(self, ctx: RuleContext) -> MockResult:
        out = [trace(ctx)]
        set_resp(ctx, out)
        return MockResult(
            statements=out,
            diagnostics=[],
        )


CICS_RULES = [
    ReturnRule(),
    AbendRule(),
    LinkRule(),
    FileRule(),
    CounterRule(),
    QueueRule(),
    TerminalRule(),
    TimeRule(),
    AssignRule(),
    ContainerRule(),
    GetmainRule(),
    NoOpRule(),
]
