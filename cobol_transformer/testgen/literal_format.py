"""COBOL literal construction and fixed-format layout for harness statements.

Two jobs, both settled against GnuCOBOL rather than assumed.

**Literals that fit the receiving field.**  A value captured from an oracle run
is turned back into a literal that compares equal to the field it came from.
The forms below were each verified against ``cobc`` 3.1.2::

    PIC X(20)      'hello'          comparison space-pads the shorter side
    PIC 9(4)       0070             leading zeros are legal in a numeric literal
    PIC S9(4) COMP -0005            DISPLAY renders the sign; ``-0005`` matches
    PIC S9(3)V99   +012.34          DISPLAY renders ``+`` and a real point
    PIC ZZZ9.99    '  42.50'        numeric-edited compares as characters
    all spaces     SPACES           ``''`` is not a valid COBOL literal

**Continuation that does not corrupt the literal.**  In fixed format the
content of a continued literal runs through *column 72*, so a line broken short
of it silently embeds the intervening spaces into the value -- a mismatch that
compiles cleanly and fails at runtime.  Every line emitted mid-literal is
therefore padded to exactly column 72 and resumed after a ``-`` in column 7.  A
literal is never split between the two halves of an escaped ``''`` pair.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

from ..analysis.pic_parser import PicCategory, PicInfo
from ..errors import TransformError
from ..linetools import CODE_END, DEFAULT_AREA_B_INDENT, INDICATOR_COL

#: Column (0-based, exclusive) that generated code must never cross.
MAX_COL = CODE_END
CONT_EXTRA_INDENT = 4

#: Longest field this module will build a comparison literal for.  Beyond it a
#: check is reported as unsupported rather than emitted -- a 32K commarea group
#: is not something to inline into an IF.
MAX_CHECKABLE_LENGTH = 160

_NUMERIC_LITERAL = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_PRINTABLE = re.compile(r"^[\x20-\x7e]*$")


class LiteralError(TransformError):
    """A value cannot be expressed as a literal legal for its field."""


# -- literal construction --------------------------------------------------

def cobol_string_literal(value: str) -> str:
    """Quote ``value`` as a COBOL alphanumeric literal, doubling inner quotes.

    Mirrors ``mocks.codegen.cobol_string_literal`` but maps the empty string to
    ``SPACES``: ``''`` is a zero-length literal, which COBOL does not accept.
    """
    if value == "":
        return "SPACES"
    return "'" + value.replace("'", "''") + "'"


def is_literal_token(part: str) -> bool:
    """True when ``part`` is a quoted literal, i.e. splittable across lines."""
    return len(part) >= 2 and part.startswith("'") and part.endswith("'")


def _numeric_literal(pic: PicInfo, value: str) -> str:
    text = value.strip()
    if text == "":
        return "0"
    if not _NUMERIC_LITERAL.match(text):
        raise LiteralError(
            f"value {value!r} is not a valid numeric literal for PIC {pic.raw!r}"
        )
    sign, digits = "", text
    if text[0] in "+-":
        sign, digits = text[0], text[1:]
    if sign == "-" and not pic.signed:
        raise LiteralError(
            f"negative value {value!r} does not fit unsigned PIC {pic.raw!r}"
        )
    whole, _, frac = digits.partition(".")
    if pic.digits and len(whole.lstrip("0") or "0") > pic.digits:
        raise LiteralError(
            f"value {value!r} has more than {pic.digits} integer digits "
            f"for PIC {pic.raw!r}"
        )
    if frac and pic.decimals and len(frac) > pic.decimals:
        raise LiteralError(
            f"value {value!r} has more than {pic.decimals} decimal places "
            f"for PIC {pic.raw!r}"
        )
    if frac and not pic.decimals:
        raise LiteralError(
            f"value {value!r} has a fraction but PIC {pic.raw!r} has no decimals"
        )
    return text


def _alphanumeric_literal(pic: PicInfo, value: str) -> str:
    # A field's own trailing blanks are not part of its value: COBOL pads the
    # shorter operand of a comparison, so the stripped form compares equal.
    text = value.rstrip()
    # For a numeric-edited picture, ``length`` counts digits, not character
    # positions: PIC +9(5) reports 5 but occupies 6 columns, and DISPLAY duly
    # renders "+00100".  Enforcing it here would reject the field's own value.
    checked_length = 0 if pic.category is PicCategory.NUMERIC_EDITED else pic.length
    if checked_length and len(text) > checked_length:
        raise LiteralError(
            f"value of length {len(text)} does not fit PIC {pic.raw!r} "
            f"(length {pic.length})"
        )
    if not _PRINTABLE.match(text):
        raise LiteralError(
            "value contains non-printable characters and cannot be written "
            "as a literal"
        )
    return cobol_string_literal(text)


def pic_info_to_move_literal(pic: Optional[PicInfo], value: str) -> str:
    """A literal legal as the sending operand of ``MOVE ... TO <field>``."""
    if pic is not None and pic.category is PicCategory.NUMERIC:
        return _numeric_literal(pic, value)
    return _alphanumeric_literal(pic or PicInfo(PicCategory.UNKNOWN), value)


def pic_info_to_condition_literal(pic: Optional[PicInfo], value: str) -> str:
    """A literal legal as the right-hand operand of ``IF <field> = ...``.

    Formatting matches :func:`pic_info_to_move_literal` with one deliberate
    divergence, which is why the two are separate functions.  An *observed*
    value is evidence about a field, not an instruction to it: a numeric field
    that DISPLAYs as blanks holds no number at all -- it was never initialised.
    Writing ``0`` there, as the MOVE form does for an empty operand, would
    assert something false and fail at runtime against the very field the value
    was read from.  Such a field is refused, so the caller reports it as not
    comparable instead of asserting a wrong literal.
    """
    if (
        pic is not None
        and pic.category is PicCategory.NUMERIC
        and value.strip() == ""
    ):
        raise LiteralError(
            "field displays as blanks, so it holds no numeric value to compare "
            "(it was never initialised on this path)"
        )
    return pic_info_to_move_literal(pic, value)


def unsupported_reason(pic: Optional[PicInfo], value: str) -> Optional[str]:
    """``None`` when ``value`` can be compared in COBOL, else why it cannot."""
    if pic is not None and pic.length > MAX_CHECKABLE_LENGTH:
        return (
            f"field length {pic.length} exceeds the {MAX_CHECKABLE_LENGTH}-character "
            "limit for an inline comparison"
        )
    # A group item has no PICTURE and so no declared length; its dumped value is
    # the only evidence of how big it is, and a 32K commarea must not become a
    # 32K literal.
    if len(value.rstrip()) > MAX_CHECKABLE_LENGTH:
        return (
            f"value length {len(value.rstrip())} exceeds the "
            f"{MAX_CHECKABLE_LENGTH}-character limit for an inline comparison"
        )
    try:
        pic_info_to_condition_literal(pic, value)
    except LiteralError as exc:
        return str(exc)
    return None


# -- fixed-format layout ---------------------------------------------------

def _continuation_prefix() -> str:
    return " " * INDICATOR_COL + "-" + " " * CONT_EXTRA_INDENT


def _split_point(escaped: str, room: int) -> int:
    """How many characters may be taken without splitting an escaped ``''``."""
    take = min(room, len(escaped))
    # Never end a chunk on the first half of an escaped quote pair: the line
    # would close the literal early and the next line would reopen it shifted.
    while take > 0 and (take - len(escaped[:take].rstrip("'"))) % 2:
        take -= 1
    return take


def render_harness_statement(
    parts: Sequence[str],
    indent: int = DEFAULT_AREA_B_INDENT,
    period: bool = False,
) -> List[str]:
    """Lay one generated statement out as fixed-format lines.

    ``parts`` are whitespace-separated tokens; any token that
    :func:`is_literal_token` accepts may be broken across continuation lines,
    every other token is placed whole.  No emitted line crosses column 72.
    """
    indent = max(indent, DEFAULT_AREA_B_INDENT)
    cont_indent = min(indent + CONT_EXTRA_INDENT, MAX_COL - 24)
    lines: List[str] = []
    cur = " " * indent

    def line_is_empty() -> bool:
        return not cur.strip()

    def wrap() -> None:
        nonlocal cur
        lines.append(cur.rstrip())
        cur = " " * cont_indent

    for part in parts:
        if not part:
            continue
        sep = "" if line_is_empty() else " "
        if len(cur) + len(sep) + len(part) <= MAX_COL:
            cur += sep + part
            continue
        if not is_literal_token(part):
            if not line_is_empty():
                wrap()
            cur += part              # an over-long bare token is left intact
            continue

        # A literal that does not fit: move it whole onto a fresh line when it
        # fits there, otherwise break it across continuation lines.
        if not line_is_empty() and cont_indent + len(part) <= MAX_COL:
            wrap()
            cur += part
            continue
        # It has to be split either way, so start it here rather than burning
        # a line on the tokens already placed.
        escaped = part[1:-1]
        cur += sep + "'"
        i = 0
        while True:
            room = MAX_COL - len(cur)
            rest = escaped[i:]
            if len(rest) + 1 <= room:        # the rest plus its closing quote
                cur += rest + "'"
                break
            take = _split_point(rest, room)
            if take <= 0:                    # pathological: no usable room
                raise LiteralError(
                    "literal cannot be laid out within column 72 at this indent"
                )
            cur += rest[:take]
            i += take
            # A mid-literal line must reach exactly column 72, or the columns
            # it stops short of become spaces inside the value.
            lines.append(cur.ljust(MAX_COL))
            cur = _continuation_prefix() + "'"

    if period:
        if len(cur) + 1 <= MAX_COL:
            cur += "."
        else:
            lines.append(cur.rstrip())
            cur = " " * cont_indent + "."
    lines.append(cur.rstrip())
    return lines
