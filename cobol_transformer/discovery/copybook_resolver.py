"""Resolve ``COPY``/``EXEC SQL INCLUDE`` names to copybook text.

Search order (design plan section 4.3):

1. each ``--copybooks`` directory, in the order given
2. the main program's own directory (the flat ``genapp-files/src`` layout)

Extensions tried per directory: ``.cpy``, ``.CPY``, ``.cbl``, ``.CBL`` and the
bare name, matched case-insensitively.

Two names in this corpus have no copybook file on disk and are supplied by
built-in providers instead:

``SQLCA``
    The DB2 communication area.  It is a fixed, standard layout; DB2 supplies it
    at precompile time on the mainframe.  Emitting the real layout means
    ``SQLCODE`` and friends become ordinary WORKING-STORAGE the mocks can move
    into, with no synthesised declarations needed.
``SSMAP``
    The BMS symbolic map, generated from ``ssmap.bms`` (see ``inline.bms``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..errors import CopybookNotFoundError
from ..inline.bms import generate_symbolic_map

_EXTENSIONS = (".cpy", ".CPY", ".cbl", ".CBL", "")

# The standard DB2 SQLCA, as the DB2 precompiler would expand INCLUDE SQLCA.
SQLCA_TEXT = """\
      *****************************************************************
      * SQLCA - DB2 SQL communication area (standard layout).         *
      * Supplied by cobol_transformer: DB2 provides this at precompile*
      * time on z/OS, so no copybook file exists in the source tree.  *
      *****************************************************************
       01  SQLCA.
           05  SQLCAID            PIC X(8).
           05  SQLCABC            PIC S9(9) COMP-5.
           05  SQLCODE            PIC S9(9) COMP-5.
           05  SQLERRM.
               49  SQLERRML       PIC S9(4) COMP-5.
               49  SQLERRMC       PIC X(70).
           05  SQLERRP            PIC X(8).
           05  SQLERRD            OCCURS 6 TIMES
                                  PIC S9(9) COMP-5.
           05  SQLWARN.
               10  SQLWARN0       PIC X.
               10  SQLWARN1       PIC X.
               10  SQLWARN2       PIC X.
               10  SQLWARN3       PIC X.
               10  SQLWARN4       PIC X.
               10  SQLWARN5       PIC X.
               10  SQLWARN6       PIC X.
               10  SQLWARN7       PIC X.
               10  SQLWARN8       PIC X.
               10  SQLWARN9       PIC X.
               10  SQLWARNA       PIC X.
           05  SQLSTATE           PIC X(5).
"""


@dataclass
class ResolvedCopybook:
    name: str
    text: str
    path: str          # real path, or a "<builtin:...>" pseudo-path
    synthesized: bool  # True when produced by a built-in provider


class CopybookResolver:
    """Search-path resolution with built-in providers and a small cache."""

    def __init__(
        self,
        search_dirs: Sequence[str],
        source_dir: Optional[str] = None,
        enable_builtins: bool = True,
    ) -> None:
        dirs: List[str] = [os.path.abspath(d) for d in search_dirs]
        if source_dir:
            src = os.path.abspath(source_dir)
            if src not in dirs:
                dirs.append(src)
        self.search_dirs = dirs
        self.enable_builtins = enable_builtins
        self._cache: Dict[Tuple[str, str], ResolvedCopybook] = {}
        self._builtins: Dict[str, Callable[[], ResolvedCopybook]] = {
            "SQLCA": self._builtin_sqlca,
            "SSMAP": self._builtin_ssmap,
        }
        # Names resolved from disk this run, for the manifest.
        self.resolved: Dict[str, ResolvedCopybook] = {}

    # -- built-in providers --------------------------------------------------

    def _builtin_sqlca(self) -> ResolvedCopybook:
        return ResolvedCopybook("SQLCA", SQLCA_TEXT, "<builtin:SQLCA>", True)

    def _builtin_ssmap(self) -> ResolvedCopybook:
        """Generate the SSMAP symbolic map from whichever ``.bms`` we can find."""
        for d in self.search_dirs:
            for cand in ("ssmap.bms", "SSMAP.bms", "SSMAP.BMS"):
                p = os.path.join(d, cand)
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        bms = fh.read()
                    return ResolvedCopybook(
                        "SSMAP", generate_symbolic_map(bms), f"<generated:{p}>", True
                    )
        raise CopybookNotFoundError(
            "SSMAP is referenced but neither a copybook nor ssmap.bms was found on "
            f"the search path: {self.search_dirs}"
        )

    # -- resolution ----------------------------------------------------------

    def _find_on_disk(self, name: str) -> Optional[str]:
        lowered = name.lower()
        for d in self.search_dirs:
            if not os.path.isdir(d):
                continue
            # Exact-name attempts first, then a case-insensitive directory scan.
            for ext in _EXTENSIONS:
                p = os.path.join(d, name + ext)
                if os.path.isfile(p):
                    return p
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            for entry in entries:
                stem, ext = os.path.splitext(entry)
                if stem.lower() == lowered and ext.lower() in (
                    ".cpy",
                    ".cbl",
                    "",
                ):
                    p = os.path.join(d, entry)
                    if os.path.isfile(p):
                        return p
        return None

    def resolve(self, name: str, library: Optional[str] = None) -> ResolvedCopybook:
        """Resolve ``name`` to copybook text, raising if it cannot be found.

        ``library`` (from ``COPY x OF/IN lib``) is treated as a best-effort
        subdirectory hint; no corpus example exercises it.
        """
        key = name.upper()
        # The cache key must include the library qualifier: two members named
        # alike in different libraries (COPY X OF LIBA. / COPY X OF LIBB.)
        # are different copybooks and must not collide on a shared cache slot.
        cache_key = (key, library.upper() if library else "")
        if cache_key in self._cache:
            return self._cache[cache_key]

        # A real file always wins over a built-in provider.
        path: Optional[str] = None
        if library:
            hint = CopybookResolver(
                [os.path.join(d, library) for d in self.search_dirs],
                enable_builtins=False,
            )
            path = hint._find_on_disk(name)
        if path is None:
            path = self._find_on_disk(name)

        if path is not None:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rc = ResolvedCopybook(key, text, os.path.abspath(path), False)
        elif self.enable_builtins and key in self._builtins:
            rc = self._builtins[key]()
        else:
            raise CopybookNotFoundError(
                f"copybook {name!r} not found on search path: {self.search_dirs}"
            )

        self._cache[cache_key] = rc
        self.resolved[key] = rc
        return rc
