"""Decide which AST nodes must not survive verbatim into the output.

Only nodes matched here are ever touched by the rewriter; everything else --
data definitions, control flow, paragraph labels -- is guaranteed untouched
because it never enters the replacement list.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

from ..ast_client.ast_model import AstNode


class Category(str, Enum):
    CICS = "cics"                 # EXEC CICS ... END-EXEC
    SQL = "sql"                   # EXEC SQL ... END-EXEC
    DFHRESP = "dfhresp"           # DFHRESP(cond) sub-expression
    EXEC_UNKNOWN = "exec_unknown"  # EXEC of an unrecognised dialect


@dataclass(frozen=True)
class ClassifierRule:
    name: str
    predicate: Callable[[AstNode], bool]
    category: Category
    #: True when the whole statement is commented out and replaced by a mock;
    #: False for sub-expressions substituted in place inside live code.
    is_statement: bool = True


def is_exec_cics(node: AstNode) -> bool:
    return node.node_type == "ExecEndExec" and node.sql_or_cics == "CICS"


def is_exec_sql(node: AstNode) -> bool:
    return node.node_type == "ExecEndExec" and node.sql_or_cics == "SQL"


def is_exec_other(node: AstNode) -> bool:
    return node.node_type == "ExecEndExec" and node.sql_or_cics not in ("CICS", "SQL")


def is_dfhresp_macro(node: AstNode) -> bool:
    """``DFHRESP(...)``/``DFHRESP2(...)`` used inside an ordinary condition.

    This node sits inside live code (typically an ``IF``), so it is substituted
    in place rather than commented out -- commenting its line would break the
    enclosing statement.
    """
    return node.node_type in ("CicsDFHRESPmacro", "CicsDFHRESP2macro")


DEFAULT_RULES: List[ClassifierRule] = [
    ClassifierRule("exec_cics", is_exec_cics, Category.CICS, True),
    ClassifierRule("exec_sql", is_exec_sql, Category.SQL, True),
    ClassifierRule("exec_other", is_exec_other, Category.EXEC_UNKNOWN, True),
    ClassifierRule("dfhresp", is_dfhresp_macro, Category.DFHRESP, False),
]


class NodeClassifier:
    """Registry of unsupported-node predicates."""

    def __init__(self, rules: Optional[List[ClassifierRule]] = None) -> None:
        self.rules = list(rules if rules is not None else DEFAULT_RULES)

    def classify(self, node: AstNode) -> Optional[ClassifierRule]:
        for rule in self.rules:
            if rule.predicate(node):
                return rule
        return None

    def is_pruned(self, node: AstNode) -> bool:
        """Whether to stop descending: EXEC subtrees are re-tokenisation noise.

        DFHRESP nodes are *not* pruned by this check because they never contain
        further nodes of interest, but pruning EXEC blocks matters -- their
        children would otherwise produce spurious overlapping matches.
        """
        return node.node_type == "ExecEndExec"
