"""Deterministic placeholder values, chosen from a field's PICTURE and name.

Every value comes from a static table plus optional name heuristics -- no clock,
no randomness -- so the same input always produces byte-identical output.  That
determinism is what makes golden-file tests and reproducible builds possible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..analysis.pic_parser import PicCategory
from ..analysis.symbol_table import Symbol
from .codegen import cobol_string_literal

DEFAULT_TEXT = "DUMMY"
DEFAULT_DATE = "2024-01-01"
DEFAULT_DATE_COMPACT = "20240101"
DEFAULT_TIME = "12:00:00"
DEFAULT_TIME_COMPACT = "120000"


@dataclass
class DummyValueConfig:
    """Tunable defaults; overridable from the rule-config file."""

    seed: int = 1
    text: str = DEFAULT_TEXT
    flag_char: str = "Y"
    numeric_default: int = 0
    generated_numeric: int = 1


def _name_has(name: str, *needles: str) -> bool:
    upper = name.upper()
    return any(n in upper for n in needles)


def literal_for(symbol: Symbol, config: Optional[DummyValueConfig] = None) -> Optional[str]:
    """A COBOL literal suitable for ``MOVE`` into ``symbol``, or None to skip.

    Returns None for fields that must not be given a fabricated value -- pointers
    (a bogus address risks a runtime fault when dereferenced) and anything whose
    PICTURE could not be interpreted.
    """
    cfg = config or DummyValueConfig()
    if symbol.is_pointer:
        return None

    pic = symbol.pic
    name = symbol.name

    if pic.category is PicCategory.NUMERIC:
        if _name_has(name, "NUM", "-ID", "ID-", "COUNT", "CNT", "SEQ"):
            value = cfg.generated_numeric
        else:
            value = cfg.numeric_default
        return str(value)

    if pic.category is PicCategory.NUMERIC_EDITED:
        return str(cfg.numeric_default)

    if pic.category in (PicCategory.ALPHANUMERIC, PicCategory.ALPHABETIC):
        length = pic.length or 1
        return cobol_string_literal(_text_for(name, length, cfg))

    return None


def _text_for(name: str, length: int, cfg: DummyValueConfig) -> str:
    """Pick alphanumeric content by name shape, then fit it to ``length``.

    The literal is only ever *truncated*, never space-padded: ``MOVE`` already
    pads an alphanumeric receiving field on the right, so padding here would add
    nothing but would push long literals past column 72, where they would need
    continuation lines to stay legal.
    """
    if length == 1:
        if _name_has(name, "FLAG", "-IND", "IND-", "-SW", "SW-"):
            return cfg.flag_char
        return " "

    if _name_has(name, "DATE", "-DOB", "DOB-"):
        base = DEFAULT_DATE if length >= 10 else DEFAULT_DATE_COMPACT
    elif _name_has(name, "TIME"):
        base = DEFAULT_TIME if length >= 8 else DEFAULT_TIME_COMPACT
    else:
        base = cfg.text

    return base[:length]


def move_statement(target: str, symbol: Optional[Symbol],
                   config: Optional[DummyValueConfig] = None) -> Optional[str]:
    """``MOVE <literal> TO <target>`` for ``symbol``, or None when unsuitable."""
    if symbol is None:
        return None
    lit = literal_for(symbol, config)
    if lit is None:
        return None
    return f"MOVE {lit} TO {target}"
