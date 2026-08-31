"""Diagnostic records and the exception hierarchy for the transformer."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class Diagnostic:
    """One machine-readable finding, carried through the pipeline into the manifest."""

    code: str
    message: str
    severity: Severity = Severity.WARNING
    file: Optional[str] = None
    line: Optional[int] = None
    col: Optional[int] = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.file is not None:
            d["file"] = self.file
        if self.line is not None:
            d["line"] = self.line
        if self.col is not None:
            d["col"] = self.col
        if self.detail:
            d["detail"] = self.detail
        return d

    def __str__(self) -> str:  # pragma: no cover - display only
        loc = ""
        if self.file:
            loc = self.file
            if self.line:
                loc += f":{self.line}"
                if self.col:
                    loc += f":{self.col}"
            loc += ": "
        return f"{self.severity.value}: {loc}{self.code}: {self.message}"


class TransformError(Exception):
    """Base class for every fatal transformer error."""


class InputError(TransformError):
    """The main program file is missing, unreadable, or not plausible COBOL."""


class CopybookNotFoundError(TransformError):
    """A COPY/INCLUDE target could not be resolved on the search path."""


class CopybookCycleError(TransformError):
    """A COPY chain re-entered a copybook already being expanded."""


class AstUnavailableError(TransformError):
    """The AST backend could not produce a tree for the given source."""


class AnchorError(TransformError):
    """Anchoring invariants were violated in a way that makes output unsafe."""
