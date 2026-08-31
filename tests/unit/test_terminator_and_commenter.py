"""Terminator fidelity and comment-preserving insertion.

These cover the two properties that keep control flow intact: a mock carries the
same sentence terminator the original had, and commenting a statement never
disturbs code that shares its lines.
"""
import pytest

from cobol_transformer.analysis.anchor import ReplacementRange
from cobol_transformer.analysis.node_classifier import Category
from cobol_transformer.inline.lexer import SourceLexer
from cobol_transformer.linetools import LineIndex
from cobol_transformer.mocks.codegen import render_statements
from cobol_transformer.rewrite.commenter import build_comment_block, purity_error
from cobol_transformer.rewrite.terminator import annotate_terminators


def _range_for_first_exec(text: str) -> ReplacementRange:
    blk = SourceLexer(text).exec_blocks[0]
    return ReplacementRange(
        start=blk.start, end=blk.end, node=None, category=Category.CICS,
        rule_name="t", is_statement=True, source_text=blk.text,
    )


def test_period_following_statement_is_detected_and_absorbed():
    text = "       EXEC CICS RETURN END-EXEC.\n       MOVE 1 TO A.\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    assert rng.had_trailing_period is True
    assert text[rng.term_end - 1] == "."


def test_statement_without_period_keeps_range():
    text = "       EXEC CICS RETURN END-EXEC\n       MOVE 1 TO A\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    assert rng.had_trailing_period is False
    assert rng.term_end == rng.end


def test_period_on_a_later_line_still_belongs_to_the_statement():
    text = "       EXEC CICS RETURN END-EXEC\n       .\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    assert rng.had_trailing_period is True


def test_intervening_statement_means_no_terminator():
    text = "       EXEC CICS RETURN END-EXEC\n       MOVE 1 TO A.\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    # The period belongs to the MOVE, not to the EXEC.
    assert rng.had_trailing_period is False


def test_codegen_emits_period_only_when_original_had_one():
    with_period = render_statements(["DISPLAY 'X'", "MOVE 0 TO A"], 11, True)
    assert with_period[-1].rstrip().endswith(".")
    assert not with_period[0].rstrip().endswith(".")

    without = render_statements(["DISPLAY 'X'", "MOVE 0 TO A"], 11, False)
    assert not without[-1].rstrip().endswith(".")


def test_codegen_never_exceeds_column_72():
    long_stmt = "DISPLAY " + " ".join(f"FIELD-NUMBER-{i}" for i in range(30))
    for line in render_statements([long_stmt], 11, True):
        assert len(line) <= 72


def test_commenter_marks_every_line_of_a_multiline_statement():
    text = (
        "       EXEC CICS READ FILE('K')\n"
        "            INTO(WS-REC)\n"
        "       END-EXEC.\n"
    )
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    block = build_comment_block(text, LineIndex(text), rng)
    assert block.last_line - block.first_line == 2
    assert all(l[6] == "*" for l in block.lines)


def test_commenter_leaves_blank_lines_untouched():
    text = "       EXEC CICS READ\n\n       END-EXEC.\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    block = build_comment_block(text, LineIndex(text), rng)
    assert block.lines[1] == ""


def test_purity_check_rejects_shared_line():
    text = "       MOVE 1 TO A  EXEC CICS RETURN END-EXEC.\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    diag = purity_error(text, LineIndex(text), rng)
    assert diag is not None
    assert diag.code == "E-COMMENT-LINE-NOT-PURE"


def test_purity_check_accepts_own_line():
    text = "       EXEC CICS RETURN END-EXEC.\n"
    rng = _range_for_first_exec(text)
    annotate_terminators(text, [rng])
    assert purity_error(text, LineIndex(text), rng) is None
