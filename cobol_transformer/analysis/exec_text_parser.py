"""Parse the raw text inside an EXEC block.

The AST reports an ``EXEC`` block's contents as one unparsed string (design plan
section 1.3, Limitation 2), so the option structure has to be recovered here.
The grammar is small and regular: a verb, then options that are either bare
keywords (``UPDATE``, ``NOHANDLE``) or ``KEYWORD(argument)``.

Nothing here guesses: an option list that cannot be tokenised cleanly is
reported so the caller can fall back to the generic rule rather than a
verb-specific rule acting on half-understood options.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Multi-word CICS verbs whose second token is part of the verb identity.
_TWO_WORD_VERBS = {
    ("SEND", "MAP"), ("SEND", "TEXT"), ("SEND", "CONTROL"), ("SEND", "PAGE"),
    ("RECEIVE", "MAP"),
    ("WRITEQ", "TS"), ("WRITEQ", "TD"),
    ("READQ", "TS"), ("READQ", "TD"),
    ("DELETEQ", "TS"), ("DELETEQ", "TD"),
    ("GET", "COUNTER"), ("GET", "CONTAINER"),
    ("PUT", "CONTAINER"),
    ("DEFINE", "COUNTER"), ("DELETE", "COUNTER"), ("QUERY", "COUNTER"),
    ("UPDATE", "COUNTER"),
    ("HANDLE", "CONDITION"), ("HANDLE", "AID"), ("HANDLE", "ABEND"),
    ("IGNORE", "CONDITION"),
}

_OPTION = re.compile(
    r"([A-Za-z][A-Za-z0-9]*)\s*(\(\s*)?",
)


@dataclass
class ExecCommand:
    """A parsed EXEC block."""

    dialect: str                       # "CICS" | "SQL" | "UNKNOWN"
    verb: str                          # e.g. "LINK", "SEND MAP", "SELECT"
    options: Dict[str, str] = field(default_factory=dict)   # KEYWORD -> arg text
    flags: List[str] = field(default_factory=list)          # bare keywords
    raw: str = ""
    parse_ok: bool = True

    def option(self, *names: str) -> Optional[str]:
        for n in names:
            v = self.options.get(n.upper())
            if v is not None:
                return v
        return None

    def has_flag(self, name: str) -> bool:
        return name.upper() in self.flags


def _strip_wrapper(body: str) -> str:
    """Remove a leading ``EXEC CICS``/``EXEC SQL`` and a trailing ``END-EXEC``."""
    t = re.sub(r"^\s*EXEC\s+(?:CICS|SQL)\b", "", body, count=1, flags=re.IGNORECASE)
    t = re.sub(r"\bEND-EXEC\b\s*\.?\s*$", "", t, flags=re.IGNORECASE)
    return t.strip()


def _match_paren(text: str, open_idx: int) -> int:
    """Index just past the ``)`` matching the ``(`` at ``open_idx``.

    Parentheses inside quoted literals do not count, so ``FILE('A(B')`` parses.
    """
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            q = ch
            i += 1
            while i < n:
                if text[i] == q:
                    if i + 1 < n and text[i + 1] == q:
                        i += 2
                        continue
                    break
                i += 1
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def parse_exec(body: str, dialect: str) -> ExecCommand:
    """Parse an EXEC block body into a verb plus options."""
    text = _strip_wrapper(body)
    if dialect == "SQL":
        return _parse_sql(text)
    return _parse_cics(text)


def _parse_cics(text: str) -> ExecCommand:
    tokens = text.split()
    if not tokens:
        return ExecCommand("CICS", "", raw=text, parse_ok=False)

    # The verb is the first token, extended when it forms a known two-word verb.
    first = re.split(r"[(\s]", tokens[0])[0].upper()
    verb = first
    consumed_chars = len(first)
    if len(tokens) > 1:
        second = re.split(r"[(\s]", tokens[1])[0].upper()
        if (first, second) in _TWO_WORD_VERBS:
            verb = f"{first} {second}"
            second_at = text.upper().find(second, consumed_chars)
            after = second_at + len(second)
            # A qualifier that carries its own argument -- GET COUNTER(name),
            # SEND MAP('X') -- is *also* an option of the verb, so leave it in
            # the option stream.  A bare qualifier (WRITEQ TS, HANDLE AID) is
            # part of the verb alone and is consumed here.
            if not (after < len(text) and text[after:].lstrip()[:1] == "("):
                consumed_chars = after

    cmd = ExecCommand("CICS", verb, raw=text)
    rest = text[consumed_chars:]

    i = 0
    n = len(rest)
    while i < n:
        ch = rest[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        m = re.match(r"[A-Za-z][A-Za-z0-9]*", rest[i:])
        if not m:
            # Unexpected punctuation: record and keep going rather than guess.
            cmd.parse_ok = False
            i += 1
            continue
        name = m.group(0).upper()
        j = i + m.end()
        while j < n and rest[j].isspace():
            j += 1
        if j < n and rest[j] == "(":
            close = _match_paren(rest, j)
            if close == -1:
                cmd.parse_ok = False
                break
            cmd.options[name] = rest[j + 1 : close - 1].strip()
            i = close
        else:
            cmd.flags.append(name)
            i = i + m.end()
    return cmd


_SQL_HOSTVAR = re.compile(r":\s*([A-Za-z0-9$#@_-]+(?:\s*\.\s*[A-Za-z0-9$#@_-]+)?)")


def _parse_sql(text: str) -> ExecCommand:
    tokens = text.split()
    verb = tokens[0].upper() if tokens else ""
    # DECLARE <name> [attrs...] CURSOR FOR ... is its own verb form; the
    # attributes between the name and CURSOR vary (INSENSITIVE SCROLL, WITH
    # HOLD, ...), so CURSOR is looked for rather than assumed to be token 2.
    if verb == "DECLARE" and len(tokens) >= 3:
        head = [t.upper() for t in tokens[1:6]]
        if "CURSOR" in head:
            verb = "DECLARE CURSOR"
        elif "TABLE" in head:
            verb = "DECLARE TABLE"
    cmd = ExecCommand("SQL", verb, raw=text)

    if verb in ("DECLARE CURSOR", "DECLARE TABLE"):
        cmd.options["CURSOR"] = tokens[1]
    elif verb in ("OPEN", "CLOSE") and len(tokens) >= 2:
        cmd.options["CURSOR"] = tokens[1]
    elif verb == "FETCH" and len(tokens) >= 2:
        cmd.options["CURSOR"] = tokens[1]

    # Host variables, in order of appearance, de-duplicated.
    seen: List[str] = []
    for m in _SQL_HOSTVAR.finditer(text):
        name = re.sub(r"\s+", "", m.group(1))
        if name not in seen:
            seen.append(name)
    cmd.options["_HOSTVARS"] = ",".join(seen)

    # The INTO list of a SELECT/FETCH is what a mock must populate.
    into = _extract_into(text)
    if into:
        cmd.options["_INTO"] = ",".join(into)

    tbl = _extract_table(text, verb)
    if tbl:
        cmd.options["_TABLE"] = tbl
    return cmd


def _extract_into(text: str) -> List[str]:
    """Host variables of an ``INTO`` clause, up to the next major keyword."""
    m = re.search(r"\bINTO\b", text, re.IGNORECASE)
    if not m:
        return []
    tail = text[m.end() :]
    stop = re.search(r"\b(FROM|WHERE|VALUES|SET|ORDER|GROUP|FOR)\b", tail, re.IGNORECASE)
    if stop:
        tail = tail[: stop.start()]
    return [re.sub(r"\s+", "", x.group(1)) for x in _SQL_HOSTVAR.finditer(tail)]


def _extract_table(text: str, verb: str) -> Optional[str]:
    patterns = {
        "SELECT": r"\bFROM\s+([A-Za-z0-9_.$#@-]+)",
        "DELETE": r"\bFROM\s+([A-Za-z0-9_.$#@-]+)",
        "INSERT": r"\bINTO\s+([A-Za-z0-9_.$#@-]+)",
        "UPDATE": r"\bUPDATE\s+([A-Za-z0-9_.$#@-]+)",
    }
    pat = patterns.get(verb)
    if not pat:
        return None
    m = re.search(pat, text, re.IGNORECASE)
    return m.group(1) if m else None


def split_arg_identifier(arg: str) -> Optional[str]:
    """The bare COBOL identifier in an option argument, or None.

    ``INTO(WS-REC)`` yields ``WS-REC``; ``FILE('KSDSCUST')`` and
    ``LENGTH(WS-A + 1)`` yield None because they are not a plain reference.
    """
    if not arg:
        return None
    a = arg.strip()
    if a[:1] in ("'", '"'):
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9$#@_-]*", a):
        return a
    return None


def literal_of(arg: str) -> Optional[str]:
    """The contents of a quoted literal argument, or None."""
    a = (arg or "").strip()
    if len(a) >= 2 and a[0] == a[-1] and a[0] in ("'", '"'):
        return a[1:-1]
    return None
