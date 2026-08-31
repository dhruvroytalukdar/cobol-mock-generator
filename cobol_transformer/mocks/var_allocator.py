"""Allocate collision-free names for synthesised WORKING-STORAGE fields.

Mocks need a small number of real variables -- chiefly per-site loop counters,
which cannot be transform-time values because the generated code is static and
a loop re-executes it.  Names are checked against the full symbol table
case-insensitively and suffixed on collision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from ..analysis.symbol_table import SymbolTable


@dataclass
class WorkingStorageItem:
    name: str
    picture: str
    value: str = "0"

    def render(self) -> str:
        return f"       01  {self.name:<22} PIC {self.picture} VALUE {self.value}."


@dataclass
class VarAllocator:
    """Hands out unique names and records the declarations they need."""

    symbols: SymbolTable
    items: List[WorkingStorageItem] = field(default_factory=list)
    _taken: Dict[str, bool] = field(default_factory=dict)

    def allocate(self, base: str, picture: str = "S9(9) COMP", value: str = "0") -> str:
        """Reserve a name derived from ``base`` and record its declaration."""
        candidate = base.upper()[:26]
        n = 0
        while candidate in self.symbols or candidate in self._taken:
            n += 1
            suffix = f"-{n}"
            candidate = (base.upper()[: 26 - len(suffix)]) + suffix
        self._taken[candidate] = True
        self.items.append(WorkingStorageItem(candidate, picture, value))
        return candidate

    def render_block(self) -> List[str]:
        if not self.items:
            return []
        return [item.render() for item in self.items]
