"""Interpret COBOL PICTURE clauses.

Only what the mock generator actually needs is derived: the storage category,
the character/digit count and whether a value must be signed, so a generated
``MOVE`` literal always fits the receiving field.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PicCategory(str, Enum):
    ALPHANUMERIC = "alphanumeric"   # X
    ALPHABETIC = "alphabetic"       # A
    NUMERIC = "numeric"             # 9
    NUMERIC_EDITED = "numeric_edited"
    UNKNOWN = "unknown"


@dataclass
class PicInfo:
    category: PicCategory
    length: int = 0        # character positions (display) or digit count
    digits: int = 0        # integer digit count for numeric
    decimals: int = 0
    signed: bool = False
    raw: str = ""

    @property
    def is_numeric(self) -> bool:
        return self.category is PicCategory.NUMERIC


_TOKEN = re.compile(r"([9AXZSVP*$,./+-])(?:\((\d+)\))?", re.IGNORECASE)


def parse_picture(pic: str) -> PicInfo:
    """Parse a PICTURE string such as ``S9(4)V99 COMP`` or ``X(20)``."""
    if not pic:
        return PicInfo(PicCategory.UNKNOWN, raw=pic or "")
    text = pic.strip().upper()
    # Drop a leading PIC/PICTURE keyword and any trailing usage clause.
    text = re.sub(r"^\s*PIC(?:TURE)?\s+(?:IS\s+)?", "", text)
    text = re.sub(
        r"\b(COMP(?:UTATIONAL)?(?:-[0-9X])?|BINARY|PACKED-DECIMAL|DISPLAY|"
        r"USAGE|IS|VALUE.*|OCCURS.*)\b.*$",
        "",
        text,
    ).strip()
    text = text.rstrip(".").strip()
    if not text:
        return PicInfo(PicCategory.UNKNOWN, raw=pic)

    signed = False
    digits = decimals = 0
    alnum = alpha = 0
    edited = False
    after_v = False

    for m in _TOKEN.finditer(text):
        sym = m.group(1).upper()
        count = int(m.group(2)) if m.group(2) else 1
        if sym == "S":
            signed = True
        elif sym == "V":
            after_v = True
        elif sym == "9":
            if after_v:
                decimals += count
            else:
                digits += count
        elif sym == "X":
            alnum += count
        elif sym == "A":
            alpha += count
        elif sym in ("Z", "*", "$", ",", ".", "+", "-"):
            edited = True
            if sym in ("Z", "*"):
                digits += count
        elif sym == "P":
            digits += count

    if alnum:
        return PicInfo(PicCategory.ALPHANUMERIC, alnum + alpha, 0, 0, False, pic)
    if alpha:
        return PicInfo(PicCategory.ALPHABETIC, alpha, 0, 0, False, pic)
    if digits or decimals:
        cat = PicCategory.NUMERIC_EDITED if edited else PicCategory.NUMERIC
        return PicInfo(cat, digits + decimals, digits, decimals, signed, pic)
    return PicInfo(PicCategory.UNKNOWN, raw=pic)
