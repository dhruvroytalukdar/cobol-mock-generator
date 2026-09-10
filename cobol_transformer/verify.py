"""Prove the transformation changed nothing but the mocked constructs.

The check reverses the transformation using the manifest -- delete the inserted
mock lines and the synthesised declarations, un-comment the statements that were
commented out, restore the LINKAGE header -- and compares the reconstruction
against the expanded source byte for byte.

If they match, then by construction every surviving line of the program,
including every branch, ``PERFORM``, ``GO TO``, paragraph and data item, is
exactly what it was.  The only differences are the constructs the manifest
declares, each of which is still present in the output as a comment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set

from .output.manifest import TransformationManifest
from .rewrite.ws_injector import BANNER, LINKAGE_NOTE, LINKAGE_NOTE2


@dataclass
class VerifyResult:
    ok: bool
    differences: List[str] = field(default_factory=list)
    reconstructed_lines: int = 0
    expected_lines: int = 0

    def summary(self) -> str:
        if self.ok:
            return "IDENTICAL - only mocked constructs differ"
        return f"{len(self.differences)} difference(s)"


def _uncomment(line: str) -> str:
    """Undo ``comment_out``: restore column 7 to a space."""
    if len(line) > 6 and line[6] == "*":
        return line[:6] + " " + line[7:]
    return line


def verify(
    expanded_text: str,
    output_text: str,
    manifest: TransformationManifest,
) -> VerifyResult:
    """Reconstruct the input from the output and diff the two."""
    out_lines = output_text.split("\n")
    drop: Set[int] = set()       # 0-based output lines to delete
    uncomment: Set[int] = set()  # 0-based output lines to un-comment

    for c in manifest.constructs:
        # An in-place substitution edits a line that is still live code; its
        # "inserted" span is that same line, so it must be restored, not
        # deleted.  Restoration happens in _is_expected_difference.
        if c.status == "substituted_in_place":
            continue
        if c.inserted_line_start and c.inserted_line_end >= c.inserted_line_start:
            for ln in range(c.inserted_line_start - 1, c.inserted_line_end):
                drop.add(ln)
        already_comment = {ln - 1 for ln in c.already_commented_lines}
        if c.commented_line_start and c.commented_line_end >= c.commented_line_start:
            for ln in range(c.commented_line_start - 1, c.commented_line_end):
                # A line that was already a comment before this tool touched it
                # (e.g. one option of a multi-line EXEC CICS command the
                # original author had disabled) must stay commented on
                # reconstruction -- only genuinely toggled lines get restored.
                if ln in already_comment:
                    continue
                uncomment.add(ln)

    # Synthesised declarations: the banner plus the 01 entries following it.
    for i, line in enumerate(out_lines):
        if line == BANNER:
            drop.add(i)
            j = i + 1
            while j < len(out_lines) and out_lines[j].lstrip().startswith("01 "):
                drop.add(j)
                j += 1
        elif line in (LINKAGE_NOTE, LINKAGE_NOTE2):
            drop.add(i)
            # The LINKAGE SECTION header itself was commented out.
            j = i + 1
            while j < len(out_lines):
                if "LINKAGE SECTION" in out_lines[j].upper():
                    uncomment.add(j)
                    break
                if out_lines[j] not in (LINKAGE_NOTE, LINKAGE_NOTE2):
                    break
                j += 1

    rebuilt: List[str] = []
    for i, line in enumerate(out_lines):
        if i in drop:
            continue
        rebuilt.append(_uncomment(line) if i in uncomment else line)

    # A DFHRESP substitution is an in-place edit inside a live statement; the
    # original text is recorded in the manifest, so restore it before diffing.
    inline_edits = [
        c for c in manifest.constructs if c.status == "substituted_in_place"
    ]
    expected = expanded_text.split("\n")

    # The PROGRAM-ID period repair is a deliberate, reported punctuation fix.
    repaired_program_id = any(
        d.get("code") == "W-SYNTAX-REPAIR" for d in manifest.diagnostics
    )

    differences: List[str] = []
    limit = max(len(rebuilt), len(expected))
    for i in range(limit):
        a = rebuilt[i] if i < len(rebuilt) else "<missing>"
        b = expected[i] if i < len(expected) else "<missing>"
        if a == b:
            continue
        if _is_expected_difference(a, b, inline_edits, repaired_program_id):
            continue
        differences.append(f"line {i + 1}:\n  got      {a!r}\n  expected {b!r}")
        if len(differences) >= 12:
            differences.append("... further differences suppressed")
            break

    return VerifyResult(
        ok=not differences,
        differences=differences,
        reconstructed_lines=len(rebuilt),
        expected_lines=len(expected),
    )


def _is_expected_difference(
    got: str, expected: str, inline_edits: List, repaired_program_id: bool
) -> bool:
    """Whether a line differs only by a change the manifest already declares."""
    if repaired_program_id and "PROGRAM-ID" in expected.upper():
        # The repair only appends the period COBOL requires.
        return got.rstrip() == expected.rstrip() + "."

    # A DFHRESP substitution replaced the macro with its numeric value; the
    # line matches once the recorded original text is put back.
    for c in inline_edits:
        original = c.raw_text
        if original and original in expected:
            restored = got
            for gen in c.generated_text:
                restored = restored.replace(gen, original, 1)
            if restored == expected:
                return True
    return False
