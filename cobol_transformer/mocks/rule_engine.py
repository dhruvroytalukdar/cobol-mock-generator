"""Rule dispatch: turn a classified construct into replacement COBOL text.

Dispatch order (design plan section 6.1):

1. ``verb_overrides`` from the rule-config file  -- highest priority
2. built-in verb-specific rules (CICS, then SQL)
3. :class:`~cobol_transformer.mocks.rules_fallback.GenericFallbackRule`, which
   always matches, so every unsupported construct receives *some* mock

Reaching the fallback for a verb that has a specific rule is reported as
``W-FALLBACK-RULE-USED`` so coverage gaps stay visible instead of silent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..analysis.anchor import ReplacementRange
from ..analysis.exec_text_parser import ExecCommand
from ..analysis.node_classifier import Category
from ..analysis.symbol_table import SymbolTable
from ..errors import Diagnostic
from .dummy_values import DummyValueConfig


@dataclass
class RuleContext:
    """Everything a rule needs to generate a mock for one construct."""

    range: ReplacementRange
    command: Optional[ExecCommand]
    category: Category
    symbols: SymbolTable
    indent: int
    had_trailing_period: bool
    #: True when the construct sits before PROCEDURE DIVISION, where no
    #: procedural statement may be emitted.
    declarative: bool
    paragraph: str
    sequence: int
    program: str
    values: DummyValueConfig = field(default_factory=DummyValueConfig)
    #: Per-cursor bookkeeping shared across the whole program.
    cursor_state: Dict[str, int] = field(default_factory=dict)
    config: Dict = field(default_factory=dict)
    #: Allocates synthesised WORKING-STORAGE names; supplied by the pipeline.
    allocator: Optional[object] = None

    @property
    def verb(self) -> str:
        return self.command.verb if self.command else ""

    def symbol(self, name: Optional[str]):
        return self.symbols.get(name) if name else None

    def allocate_counter(self, base: str) -> str:
        """A fresh WORKING-STORAGE counter for this construct.

        Loop-bounding counters must be per *site*, not per cursor name: two
        FETCH statements on the same cursor sit in different loops and each
        needs its own count.
        """
        if self.allocator is None:
            raise RuntimeError("RuleContext.allocator was not supplied")
        return self.allocator.allocate(f"{base}-{self.sequence}")


@dataclass
class MockResult:
    """What a rule produced."""

    statements: List[str] = field(default_factory=list)
    working_storage: List[str] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)
    confidence: str = "high"          # "high" | "fallback"
    #: Text substituted directly for the span, used only by sub-expression
    #: rules such as DFHRESP.
    inline_text: Optional[str] = None


class MockRule:
    """Base class for a mock generator."""

    name = "rule"

    def matches(self, ctx: RuleContext) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def generate(self, ctx: RuleContext) -> MockResult:  # pragma: no cover
        raise NotImplementedError


class RuleEngine:
    """Ordered registry with a guaranteed-matching fallback."""

    def __init__(self, rules: List[MockRule], fallback: MockRule) -> None:
        self.rules = list(rules)
        self.fallback = fallback

    def dispatch(self, ctx: RuleContext) -> tuple[MockRule, MockResult]:
        for rule in self.rules:
            if rule.matches(ctx):
                return rule, rule.generate(ctx)
        return self.fallback, self.fallback.generate(ctx)


def build_default_engine(config: Optional[Dict] = None) -> RuleEngine:
    """Assemble the built-in rule set."""
    from .rules_cics import CICS_RULES
    from .rules_eib import DfhrespRule
    from .rules_fallback import GenericFallbackRule
    from .rules_sql import SQL_RULES

    rules: List[MockRule] = [DfhrespRule()]
    rules.extend(CICS_RULES)
    rules.extend(SQL_RULES)
    return RuleEngine(rules, GenericFallbackRule())
