"""The machine-readable record of one transformation run."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ConstructRecord:
    """One detected construct and what became of it."""

    original_file: str
    original_line: int
    expanded_line_start: int
    expanded_line_end: int
    node_type: str
    category: str
    verb: str
    raw_text: str
    had_trailing_period: bool
    matched_rule: str
    confidence: str
    status: str
    commented_line_start: int = 0
    commented_line_end: int = 0
    inserted_line_start: int = 0
    inserted_line_end: int = 0
    generated_text: List[str] = field(default_factory=list)
    diagnostic_codes: List[str] = field(default_factory=list)


@dataclass
class TransformationManifest:
    program: str
    source_path: str
    output_path: str
    detection_backend: str                 # "ast" | "text-fallback"
    ast_error: Optional[str] = None
    copybooks: Dict[str, Any] = field(default_factory=dict)
    synthesized_fields: List[str] = field(default_factory=list)
    linkage_promoted: bool = False
    constructs: List[ConstructRecord] = field(default_factory=list)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    compile_result: Optional[Dict[str, Any]] = None

    # -- summary -------------------------------------------------------------

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for c in self.constructs:
            out[c.status] = out.get(c.status, 0) + 1
        return out

    @property
    def fallback_count(self) -> int:
        return sum(1 for c in self.constructs if c.confidence == "fallback")

    @property
    def skipped_count(self) -> int:
        return sum(1 for c in self.constructs if c.status.startswith("skipped"))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["summary"] = {
            "constructs": len(self.constructs),
            "by_status": self.counts(),
            "fallback_rules_used": self.fallback_count,
            "skipped": self.skipped_count,
        }
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
