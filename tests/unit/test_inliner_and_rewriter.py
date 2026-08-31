"""Copybook expansion (including REPLACING and cycles) and the rewrite pass."""
import os

import pytest

from cobol_transformer.analysis.anchor import ReplacementRange
from cobol_transformer.analysis.node_classifier import Category
from cobol_transformer.discovery.copybook_resolver import CopybookResolver
from cobol_transformer.errors import CopybookCycleError, CopybookNotFoundError
from cobol_transformer.inline.inliner import Inliner
from cobol_transformer.inline.lexer import SourceLexer
from cobol_transformer.inline.replacing import apply_replacing, parse_replacing
from cobol_transformer.rewrite.rewriter import rewrite
from cobol_transformer.rewrite.terminator import annotate_terminators


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _inliner(tmp_path, **kw):
    return Inliner(CopybookResolver([str(tmp_path)], source_dir=str(tmp_path)), **kw)


# -- REPLACING -------------------------------------------------------------

def test_replacing_identifier_is_whole_word_and_case_insensitive():
    pairs = parse_replacing("==:TAG:== BY ==WS==")
    assert apply_replacing(":TAG:-FIELD", pairs) == "WS-FIELD"

    pairs = parse_replacing("ABC BY XYZ")
    assert apply_replacing("ABC ABCD abc", pairs) == "XYZ ABCD XYZ"


def test_replacing_pseudo_text_tolerates_whitespace_runs():
    pairs = parse_replacing("==PIC   X== BY ==PIC 9==")
    assert apply_replacing("01 A PIC    X.", pairs) == "01 A PIC 9."


def test_replacing_replacement_containing_pattern_terminates():
    pairs = parse_replacing("A BY AA")
    assert apply_replacing("A A", pairs) == "AA AA"


# -- inlining --------------------------------------------------------------

def test_copy_is_expanded_with_banners(tmp_path):
    write(tmp_path, "BOOK.cpy", "       01  FROM-BOOK PIC X.\n")
    main = write(tmp_path, "M.cbl", "       WORKING-STORAGE SECTION.\n       COPY BOOK.\n")
    res = _inliner(tmp_path).inline_file(main)
    assert "FROM-BOOK" in res.text
    assert "BEGIN COPY BOOK" in res.text
    assert res.copybooks_used["BOOK"] == 1


def test_banner_lands_in_the_indicator_column(tmp_path):
    write(tmp_path, "BOOK.cpy", "       01  A PIC X.\n")
    main = write(tmp_path, "M.cbl", "           COPY BOOK.\n")
    res = _inliner(tmp_path).inline_file(main)
    for line in res.text.split("\n"):
        if "BEGIN COPY" in line:
            assert line[6] == "*"
            break
    else:
        pytest.fail("banner not emitted")


def test_duplicate_copy_is_expanded_each_time(tmp_path):
    write(tmp_path, "BOOK.cpy", "       01  A PIC X.\n")
    main = write(tmp_path, "M.cbl", "       COPY BOOK.\n       COPY BOOK.\n")
    res = _inliner(tmp_path).inline_file(main)
    assert res.text.count("01  A PIC X") == 2
    assert res.copybooks_used["BOOK"] == 2


def test_nested_copy_is_expanded(tmp_path):
    write(tmp_path, "INNER.cpy", "       01  INNER-F PIC X.\n")
    write(tmp_path, "OUTER.cpy", "       COPY INNER.\n")
    main = write(tmp_path, "M.cbl", "       COPY OUTER.\n")
    res = _inliner(tmp_path).inline_file(main)
    assert "INNER-F" in res.text


def test_copy_cycle_is_detected(tmp_path):
    write(tmp_path, "A.cpy", "       COPY B.\n")
    write(tmp_path, "B.cpy", "       COPY A.\n")
    main = write(tmp_path, "M.cbl", "       COPY A.\n")
    with pytest.raises(CopybookCycleError):
        _inliner(tmp_path).inline_file(main)


def test_missing_copybook_hard_fails_by_default(tmp_path):
    main = write(tmp_path, "M.cbl", "       COPY NOPE.\n")
    with pytest.raises(CopybookNotFoundError):
        _inliner(tmp_path).inline_file(main)


def test_missing_copybook_can_continue_with_placeholder(tmp_path):
    main = write(tmp_path, "M.cbl", "       COPY NOPE.\n")
    res = _inliner(tmp_path, continue_on_missing=True).inline_file(main)
    assert "MISSING COPYBOOK NOPE" in res.text
    assert res.diagnostics[0].code == "W-COPYBOOK-MISSING"


def test_sqlca_is_supplied_by_a_builtin(tmp_path):
    main = write(tmp_path, "M.cbl",
                 "       EXEC SQL\n         INCLUDE SQLCA\n       END-EXEC.\n")
    res = _inliner(tmp_path).inline_file(main)
    assert "SQLCODE" in res.text


# -- rewriting -------------------------------------------------------------

def _one_range(text):
    blk = SourceLexer(text).exec_blocks[0]
    rng = ReplacementRange(
        start=blk.start, end=blk.end, node=None, category=Category.CICS,
        rule_name="t", is_statement=True, source_text=blk.text,
    )
    annotate_terminators(text, [rng])
    return rng


def test_original_is_commented_not_deleted_and_mock_follows():
    text = "       MOVE 1 TO A.\n       EXEC CICS RETURN END-EXEC.\n       STOP RUN.\n"
    rng = _one_range(text)
    out = rewrite(text, [rng], {rng.start: ["           GOBACK."]}, {})
    lines = out.text.split("\n")
    # The original survives as a comment...
    assert any(l.startswith("      *") and "EXEC CICS RETURN" in l for l in lines)
    # ...immediately above its mock...
    idx = next(i for i, l in enumerate(lines) if "EXEC CICS RETURN" in l)
    assert "GOBACK" in lines[idx + 1]
    # ...and untouched code is byte-identical.
    assert "       MOVE 1 TO A." in out.text
    assert "       STOP RUN." in out.text


def test_impure_line_is_skipped_rather_than_corrupted():
    text = "       MOVE 1 TO A  EXEC CICS RETURN END-EXEC.\n"
    rng = _one_range(text)
    out = rewrite(text, [rng], {rng.start: ["           GOBACK."]}, {})
    assert out.text == text                       # nothing changed
    assert out.entries[0].status == "skipped_comment_line_not_pure"


def test_inline_substitution_keeps_the_line_live():
    text = "           IF WS-RESP NOT = DFHRESP(NORMAL)\n"
    start = text.index("DFHRESP(NORMAL)")
    rng = ReplacementRange(
        start=start, end=start + len("DFHRESP(NORMAL)"), node=None,
        category=Category.DFHRESP, rule_name="d", is_statement=False,
        source_text="DFHRESP(NORMAL)",
    )
    out = rewrite(text, [rng], {}, {start: "0"})
    assert out.text == "           IF WS-RESP NOT = 0\n"
    assert out.entries[0].status == "substituted_in_place"
