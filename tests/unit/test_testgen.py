"""Test-case generation, instrumentation and coverage scoring."""
import json

import pytest

from cobol_transformer.analysis.pic_parser import parse_picture
from cobol_transformer.analysis.symbol_table import build_symbol_table
from cobol_transformer.ast_client.ast_model import AstDocument, AstNode
from cobol_transformer.errors import TransformError
from cobol_transformer.linetools import CODE_END, INDICATOR_COL
from cobol_transformer.testgen import cfg
from cobol_transformer.testgen.instrumenter import (
    CHECK_PARAGRAPH, DUMP_PARAGRAPH, EOF_PARAGRAPH, INIT_PARAGRAPH,
    InstrumentError, _splice, instrument,
)
# Imported under another name: pytest would otherwise try to collect the
# dataclass as a test class purely because of what it is called.
from cobol_transformer.testgen.instrumenter import TestCase as Case
from cobol_transformer.testgen.literal_format import (
    LiteralError, cobol_string_literal, pic_info_to_condition_literal,
    pic_info_to_move_literal, render_harness_statement, unsupported_reason,
)
from cobol_transformer.testgen.oracle_runner import parse_dump
from cobol_transformer.testgen.run_and_report import (
    coverage_report, parse_checks, parse_coverage, summarize,
)
from cobol_transformer.testgen.variable_context import build_context


# -- a small but structurally complete program -----------------------------

PROGRAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. DEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  W-FLAG      PIC 9(2) VALUE 0.
       01  W-NAME      PIC X(20) VALUE SPACES.
       01  W-AMT       PIC S9(3)V99 VALUE 0.
       01  W-GRP.
           05  W-PART   PIC X(4).
       01  FILLER       PIC X(4).
       88  W-COND       VALUE 1.
       PROCEDURE DIVISION.
       MAINLINE SECTION.
           IF W-FLAG > 0
              GO TO SECOND-PARA.
           MOVE 'start' TO W-NAME.
       SECOND-PARA.
           IF W-FLAG = 5
              MOVE 'five' TO W-NAME
           ELSE
              MOVE 'other' TO W-NAME
           END-IF.
           DISPLAY 'done ' W-NAME.
           GOBACK.
       THIRD-PARA.
           MOVE 'third' TO W-NAME.
           GOBACK.
"""


def _pic(text):
    return parse_picture(text)


def _symbols():
    return build_symbol_table(PROGRAM)


# -- literal construction --------------------------------------------------

def test_numeric_literals_keep_the_form_display_produces():
    # DISPLAY renders a signed field with its sign and leading zeros; those
    # exact strings must round-trip back into valid numeric literals.
    assert pic_info_to_move_literal(_pic("9(4)"), "0070") == "0070"
    assert pic_info_to_move_literal(_pic("S9(4) COMP"), "-0005") == "-0005"
    assert pic_info_to_move_literal(_pic("S9(3)V99"), "+012.34") == "+012.34"
    assert pic_info_to_move_literal(_pic("9(2)"), "") == "0"


def test_numeric_literal_rejects_values_the_field_cannot_hold():
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("9(2)"), "-5")        # unsigned field
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("9(2)"), "12345")     # too many digits
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("9(4)"), "12.5")      # no decimals
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("9(4)"), "abc")


def test_alphanumeric_literal_escapes_quotes_and_maps_blank_to_spaces():
    assert pic_info_to_move_literal(_pic("X(20)"), "it's") == "'it''s'"
    # A zero-length literal is not valid COBOL, so an all-blank value has to
    # become the figurative constant instead.
    assert pic_info_to_move_literal(_pic("X(10)"), "     ") == "SPACES"
    assert cobol_string_literal("") == "SPACES"


def test_alphanumeric_literal_rejects_overlong_and_unprintable_values():
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("X(4)"), "toolong")
    with pytest.raises(LiteralError):
        pic_info_to_move_literal(_pic("X(10)"), "a\x00b")


def test_condition_literal_matches_move_literal():
    assert (pic_info_to_condition_literal(_pic("X(8)"), "hi")
            == pic_info_to_move_literal(_pic("X(8)"), "hi"))


def test_unsupported_reason_guards_group_items_with_no_declared_length():
    # A group has no PICTURE, so only the dumped value reveals its size; a 32K
    # commarea must never be inlined into an IF.
    assert unsupported_reason(None, "x" * 5000) is not None
    assert unsupported_reason(None, "short") is None


# -- fixed-format layout ---------------------------------------------------

def _reconstruct_literal(lines):
    """Rebuild a literal's value the way a fixed-format compiler reads it.

    Encodes the rule this module exists to respect: the content of a continued
    literal runs through column 72, so a line stopping short of it contributes
    the intervening columns as spaces.
    """
    value = ""
    for line in lines:
        code = line[7:CODE_END]
        quote = code.find("'")
        if quote == -1:
            continue
        rest = code[quote + 1:]
        buf, i, closed = "", 0, False
        while i < len(rest):
            if rest[i] == "'":
                if i + 1 < len(rest) and rest[i + 1] == "'":
                    buf += "'"
                    i += 2
                    continue
                closed = True
                break
            buf += rest[i]
            i += 1
        value += buf
        if closed:
            return value
        value += " " * (CODE_END - 7 - len(code))   # the compiler pads to col 72
    return value


@pytest.mark.parametrize("value", [
    "short",
    "Please enter a valid option and then retry the whole operation ag",
    "x" * 200,
    "quote ' inside a value that is long enough to need continuation aaaa",
])
def test_rendered_literals_reconstruct_to_their_original_value(value):
    lines = render_harness_statement(
        ["MOVE", cobol_string_literal(value), "TO", "W-X"], 11, period=True
    )
    assert _reconstruct_literal(lines) == value


def test_no_rendered_line_crosses_column_72():
    long_value = "y" * 400
    lines = render_harness_statement(
        ["DISPLAY", cobol_string_literal(long_value), "W-NAME"], 11, period=True
    )
    assert lines
    assert all(len(line) <= CODE_END for line in lines)


def test_continuation_lines_are_marked_and_padded_to_column_72():
    lines = render_harness_statement(
        ["MOVE", cobol_string_literal("z" * 150), "TO", "W-X"], 11, period=True
    )
    continuations = [ln for ln in lines if len(ln) > INDICATOR_COL
                     and ln[INDICATOR_COL] == "-"]
    assert continuations, "a 150-character literal must be continued"
    # Every line that a literal continues *out of* must reach column 72.
    for line in lines[:-1]:
        assert len(line) == CODE_END


def test_period_is_appended_only_when_requested():
    assert render_harness_statement(["CONTINUE"], 11, period=True)[-1].endswith(".")
    assert not render_harness_statement(["ELSE"], 11)[-1].endswith(".")


# -- variable context ------------------------------------------------------

def test_context_lists_settable_fields_and_skips_filler_and_conditions():
    ctx = build_context(PROGRAM, "DEMO")
    names = {v.name for v in ctx.variables}
    assert {"W-FLAG", "W-NAME", "W-AMT", "W-PART"} <= names
    assert "FILLER" not in names      # unnamed storage
    assert "W-COND" not in names      # an 88-level carries no storage
    assert "W-GRP" not in names       # a group takes no literal MOVE
    assert ctx.paragraphs == ["MAINLINE", "SECOND-PARA", "THIRD-PARA"]


def test_context_reports_picture_details_used_to_validate_values():
    ctx = build_context(PROGRAM, "DEMO")
    amt = ctx.variable("W-AMT")
    assert (amt.category, amt.digits, amt.decimals, amt.signed) == (
        "numeric", 3, 2, True
    )


# -- control-flow extraction ----------------------------------------------

def _node(kind, text, props=None, children=()):
    return AstNode(kind, text, dict(props or {}), list(children))


def _demo_document():
    """An AST over PROGRAM, shaped as the real serializer emits one."""
    if_else = _node(
        "IfStatement",
        "IF W-FLAG = 5\n              MOVE 'five' TO W-NAME\n           ELSE\n"
        "              MOVE 'other' TO W-NAME\n           END-IF",
        {"_IF": "IF", "_Condition": "W-FLAG = 5",
         "_StatementNextSentence": "MOVE 'five' TO W-NAME",
         "_EndIf": "END-IF", "_ELSE": "ELSE",
         "_StatementNextSentence6": "MOVE 'other' TO W-NAME"},
    )
    if_plain = _node(
        "IfStatement",
        "IF W-FLAG > 0\n              GO TO SECOND-PARA",
        {"_IF": "IF", "_Condition": "W-FLAG > 0",
         "_StatementNextSentence": "GO TO SECOND-PARA"},
    )
    # Locate the *headers*: a bare index() would match the paragraph name
    # inside "GO TO SECOND-PARA." and truncate the section's span.
    def header(name):
        return PROGRAM.index("\n       " + name + ".") + 1

    section_start = header("MAINLINE SECTION")
    second_start = header("SECOND-PARA")
    third_start = header("THIRD-PARA")
    section = _node(
        "SectionHeaderParagraph",
        PROGRAM[section_start:second_start].rstrip(),
        {},
        [_node("SectionHeader0", "MAINLINE SECTION", {"_SectionName": "MAINLINE"}),
         if_plain],
    )
    second = _node(
        "Paragraph0", PROGRAM[second_start:third_start].rstrip(),
        {"_ParagraphName": "SECOND-PARA"}, [if_else],
    )
    third = _node(
        "Paragraph0", PROGRAM[third_start:].rstrip(),
        {"_ParagraphName": "THIRD-PARA"},
    )
    return AstDocument(_node("CompilationUnit", PROGRAM, {},
                             [section, second, third]))


def test_manifest_covers_every_paragraph_and_section():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    ids = [b.id for b in manifest.blocks]
    assert "PARA-MAINLINE" in ids
    assert "PARA-SECOND-PARA" in ids
    assert "PARA-THIRD-PARA" in ids
    kinds = {b.id: b.kind for b in manifest.blocks}
    assert kinds["PARA-MAINLINE"] == "section"
    assert kinds["PARA-SECOND-PARA"] == "paragraph"


def test_if_with_else_yields_both_branches_and_a_bare_if_only_one():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    ids = [b.id for b in manifest.blocks]
    assert "IF-0001-THEN" in ids and "IF-0001-ELSE" not in ids
    assert "IF-0002-THEN" in ids and "IF-0002-ELSE" in ids


def test_branch_probes_point_at_the_branch_body_not_the_if_keyword():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    blocks = manifest.by_id()
    assert PROGRAM[blocks["IF-0001-THEN"].probe_offset:].startswith("GO TO SECOND-PARA")
    assert PROGRAM[blocks["IF-0002-THEN"].probe_offset:].startswith("MOVE 'five'")
    assert PROGRAM[blocks["IF-0002-ELSE"].probe_offset:].startswith("MOVE 'other'")


def test_paragraph_probes_land_after_the_header_period():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    for block in manifest.blocks:
        if block.kind in ("paragraph", "section"):
            assert PROGRAM[block.probe_offset - 1] == "."


def test_paragraph_line_ranges_do_not_overlap():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    routines = sorted(
        (b for b in manifest.blocks if b.kind in ("paragraph", "section")),
        key=lambda b: b.line_start,
    )
    for earlier, later in zip(routines, routines[1:]):
        assert earlier.line_end < later.line_start


def test_branch_probes_carry_no_period_but_paragraph_probes_do():
    # This is the difference that keeps an inserted probe from closing an IF
    # sentence and freeing the branch body to run unconditionally.
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    for block in manifest.blocks:
        expected = block.kind in ("paragraph", "section")
        assert block.probe_period is expected


def test_unlocatable_if_is_dropped_with_a_diagnostic_not_guessed():
    doc = AstDocument(_node("CompilationUnit", PROGRAM, {}, [
        _node("IfStatement", "IF W-FLAG > 0\n              GO TO SECOND-PARA",
              {"_IF": "IF", "_Condition": "NOT IN THE SOURCE AT ALL",
               "_StatementNextSentence": "ALSO NOT IN THE SOURCE"}),
    ]))
    manifest = cfg.build_manifest(PROGRAM, doc, "DEMO")
    assert not [b for b in manifest.blocks if b.kind.startswith("if")]
    assert any(d.code == "W-CFG-IF-NOT-LOCATED" for d in manifest.diagnostics)


# -- splicing --------------------------------------------------------------

def test_splice_preserves_the_column_of_whatever_followed():
    text = "       IF X = 1 MOVE 2 TO Y.\n"
    offset = text.index("MOVE")
    out = _splice(text, [(offset, ["           DISPLAY 'P'"])])
    lines = out.split("\n")
    assert lines[0] == "       IF X = 1 "
    assert lines[1] == "           DISPLAY 'P'"
    # The displaced statement resumes at exactly the column it started in.
    assert lines[2].index("MOVE") == offset


def test_splice_applies_multiple_insertions_without_shifting_offsets():
    text = "       AAA.\n       BBB.\n       CCC.\n"
    out = _splice(text, [
        (text.index("AAA"), ["           ONE"]),
        (text.index("BBB"), ["           TWO"]),
        (text.index("CCC"), ["           THREE"]),
    ])
    assert out.index("ONE") < out.index("AAA")
    assert out.index("TWO") < out.index("BBB")
    assert out.index("THREE") < out.index("CCC")


# -- instrumentation -------------------------------------------------------

def _case(**kw):
    base = dict(test_id="test1", program="DEMO",
                initial_values={"W-FLAG": "5"}, variables_to_check=["W-NAME"])
    base.update(kw)
    return Case(**base)


def test_oracle_mode_emits_init_moves_and_dumps():
    result = instrument(PROGRAM, _case(), _symbols(), mode="oracle")
    assert f"{INIT_PARAGRAPH}." in result.text
    assert "MOVE 5 TO W-FLAG." in result.text
    assert "'TC:DUMP:W-NAME='" in result.text
    assert DUMP_PARAGRAPH in result.text
    assert result.variables_instrumented == ["W-NAME"]


def test_init_paragraph_precedes_the_first_section_header():
    result = instrument(PROGRAM, _case(), _symbols(), mode="oracle")
    assert result.text.index(f"{INIT_PARAGRAPH}.") < result.text.index(
        "MAINLINE SECTION."
    )


def test_every_exit_point_reports_before_returning():
    result = instrument(PROGRAM, _case(), _symbols(), mode="oracle")
    assert result.exit_points == 2          # PROGRAM has two GOBACKs
    assert result.text.count(f"PERFORM {DUMP_PARAGRAPH}") == 3   # + the EOF guard


def test_eof_guard_precedes_the_trailer_body_so_fallthrough_reports_once():
    result = instrument(PROGRAM, _case(), _symbols(), mode="oracle")
    assert result.text.index(f"{EOF_PARAGRAPH}.") < result.text.index(
        f"{DUMP_PARAGRAPH}."
    )


def test_invalid_initial_value_is_refused_rather_than_emitted():
    with pytest.raises(InstrumentError) as exc:
        instrument(PROGRAM, _case(initial_values={"W-FLAG": "999999"}),
                   _symbols(), mode="oracle")
    assert "W-FLAG" in str(exc.value)


def test_unknown_variable_is_refused():
    with pytest.raises(InstrumentError):
        instrument(PROGRAM, _case(initial_values={"NO-SUCH-FIELD": "1"}),
                   _symbols(), mode="oracle")
    with pytest.raises(InstrumentError):
        instrument(PROGRAM, _case(variables_to_check=["NO-SUCH-FIELD"]),
                   _symbols(), mode="oracle")


def test_checked_mode_requires_a_frozen_test_case():
    with pytest.raises(InstrumentError) as exc:
        instrument(PROGRAM, _case(), _symbols(), mode="checked")
    assert "oracle" in str(exc.value)


def test_checked_mode_compares_against_the_frozen_value():
    case = _case(expected_values={"W-NAME": "five"})
    result = instrument(PROGRAM, case, _symbols(), mode="checked")
    assert "IF W-NAME = 'five'" in result.text
    assert "'TC:CHK:W-NAME:MATCH=Y:ACTUAL='" in result.text
    assert "'TC:CHK:W-NAME:MATCH=N:ACTUAL='" in result.text
    assert CHECK_PARAGRAPH in result.text


def test_a_value_that_cannot_be_a_literal_is_reported_not_asserted_wrongly():
    case = _case(variables_to_check=["W-GRP"],
                 expected_values={"W-GRP": "x" * 5000})
    result = instrument(PROGRAM, case, _symbols(), mode="checked")
    assert "W-GRP" in result.variables_skipped
    assert result.variables_instrumented == []
    assert any(d.code == "W-TESTGEN-UNCHECKABLE" for d in result.diagnostics)


def test_coverage_probes_are_inserted_only_in_checked_mode():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    oracle = instrument(PROGRAM, _case(), _symbols(), "oracle", manifest)
    assert "TC:COV:" not in oracle.text
    assert oracle.blocks_instrumented == []
    checked = instrument(PROGRAM, _case(expected_values={"W-NAME": "five"}),
                         _symbols(), "checked", manifest)
    assert len(checked.blocks_instrumented) == len(manifest.blocks)
    for block in manifest.blocks:
        assert f"'TC:COV:{block.id}'" in checked.text


def test_branch_probe_does_not_terminate_the_conditional_sentence():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    checked = instrument(PROGRAM, _case(expected_values={"W-NAME": "five"}),
                         _symbols(), "checked", manifest)
    for line in checked.text.split("\n"):
        if "TC:COV:IF-" in line:
            assert not line.rstrip().endswith("."), (
                "a branch probe with its own period would close the IF sentence "
                "and let the branch body run unconditionally"
            )
        if "TC:COV:PARA-" in line:
            assert line.rstrip().endswith(".")


def test_instrumented_source_stays_inside_the_code_area():
    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    checked = instrument(
        PROGRAM,
        _case(initial_values={"W-NAME": "a value that fits"},
              expected_values={"W-NAME": "five"}),
        _symbols(), "checked", manifest,
    )
    for i, line in enumerate(checked.text.split("\n"), start=1):
        assert len(line) <= CODE_END, f"line {i} runs past column 72: {line!r}"


# -- test case round-tripping ---------------------------------------------

def test_testcase_json_round_trips_and_omits_absent_expected_values(tmp_path):
    path = tmp_path / "test1.json"
    _case().write(str(path))
    assert "expected_values" not in json.loads(path.read_text())
    loaded = Case.load(str(path))
    assert not loaded.is_frozen
    # expected_values alone -- with no oracle_source -- must not count as
    # frozen: that is exactly what a real bless() run is the only source of.
    loaded.expected_values = {"W-NAME": "five"}
    loaded.write()
    assert not Case.load(str(path)).is_frozen
    loaded.oracle_source = "instrumented/DEMO/oracle/test1.cbl"
    loaded.write()
    assert Case.load(str(path)).is_frozen


# -- output parsing --------------------------------------------------------

def test_parse_dump_keeps_values_containing_separators():
    stdout = "noise\nTC:DUMP:W-NAME=a=b:c   \nTC:DUMP:W-FLAG=05\n"
    assert parse_dump(stdout) == {"W-NAME": "a=b:c", "W-FLAG": "05"}


def test_parse_dump_takes_the_last_observation():
    # Reaching an exit and also falling through would report twice; the final
    # observation is the one that describes the end of the run.
    assert parse_dump("TC:DUMP:X=one\nTC:DUMP:X=two\n") == {"X": "two"}


def test_parse_checks_reads_the_match_flag_and_actual_value():
    stdout = ("TC:CHK:W-NAME:MATCH=Y:ACTUAL=five      \n"
              "TC:CHK:W-FLAG:MATCH=N:ACTUAL=07\n")
    assert parse_checks(stdout) == {"W-NAME": (True, "five"), "W-FLAG": (False, "07")}


def test_parse_coverage_deduplicates_and_keeps_first_hit_order():
    stdout = "TC:COV:PARA-A\nTC:COV:IF-0001-THEN\nTC:COV:PARA-A\n"
    assert parse_coverage(stdout) == ["PARA-A", "IF-0001-THEN"]


# -- coverage scoring ------------------------------------------------------

def _manifest(*blocks):
    return cfg.CoverageManifest(program="DEMO", blocks=list(blocks))


def test_block_coverage_counts_only_known_blocks():
    manifest = _manifest(
        cfg.Block("PARA-A", "paragraph", "A", 1, 10),
        cfg.Block("PARA-B", "paragraph", "B", 11, 20),
    )
    report = coverage_report(manifest, ["PARA-A", "GHOST"])
    assert report["blocks_hit"] == ["PARA-A"]
    assert report["blocks_total"] == 2
    assert report["block_coverage_pct"] == 50.0
    assert report["blocks_unknown"] == ["GHOST"]


def test_line_proxy_discounts_nested_blocks_that_did_not_fire():
    # Entering a 10-line paragraph must not credit the 4-line branch inside it
    # that never ran, or a single entry would report near-total line coverage.
    manifest = _manifest(
        cfg.Block("PARA-A", "paragraph", "A", 1, 10),
        cfg.Block("IF-0001-THEN", "if-then", "IF-0001", 4, 7),
    )
    assert coverage_report(manifest, ["PARA-A"])["lines_covered"] == 6
    assert coverage_report(manifest, ["PARA-A", "IF-0001-THEN"])[
        "lines_covered"] == 10


def test_line_proxy_counts_overlapping_ranges_once():
    manifest = _manifest(
        cfg.Block("PARA-A", "paragraph", "A", 1, 10),
        cfg.Block("IF-0001-THEN", "if-then", "IF-0001", 4, 7),
    )
    report = coverage_report(manifest, ["PARA-A", "IF-0001-THEN"])
    assert report["lines_total"] == 10          # not 14
    assert report["line_coverage_pct"] == 100.0


def test_suite_summary_unions_coverage_across_tests():
    manifest = _manifest(
        cfg.Block("PARA-A", "paragraph", "A", 1, 10),
        cfg.Block("PARA-B", "paragraph", "B", 11, 20),
        cfg.Block("PARA-C", "paragraph", "C", 21, 30),
    )
    reports = [
        {"test_id": "test1", "all_match": True,
         "coverage": {"blocks_hit": ["PARA-A"]}},
        {"test_id": "test2", "all_match": False,
         "coverage": {"blocks_hit": ["PARA-B"]}},
    ]
    summary = summarize("DEMO", reports, manifest)
    assert summary["passed"] == 1 and summary["failed"] == 1
    # The union is the point of having more than one test case.
    assert summary["suite_coverage"]["blocks_hit"] == ["PARA-A", "PARA-B"]
    assert summary["suite_coverage"]["blocks_never_hit"] == ["PARA-C"]
    assert summary["suite_coverage"]["block_coverage_pct"] == pytest.approx(66.7)


# -- integration: the real toolchain --------------------------------------
#
# These exercise the two things unit tests cannot: that GnuCOBOL accepts the
# instrumented source, and that the AST server's real node shapes still yield
# the blocks this package expects.  They skip cleanly where either is absent.

import os
import shutil
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRANSFORMED = os.path.join(REPO_ROOT, "transformed", "genapp")


def _gnucobol():
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner

    runner = GnuCobolRunner()
    return runner if runner.available() else None


def _ast_available(url="http://127.0.0.1:4010"):
    from cobol_transformer.ast_client.http_client import AstClientConfig, HttpAstClient

    return HttpAstClient(AstClientConfig(base_url=url)).available()


needs_cobc = pytest.mark.skipif(_gnucobol() is None, reason="GnuCOBOL unavailable")
needs_ast = pytest.mark.skipif(not _ast_available(), reason="AST server unavailable")
needs_corpus = pytest.mark.skipif(
    not os.path.isfile(os.path.join(TRANSFORMED, "lgtestp1.cbl")),
    reason="transformed corpus unavailable",
)


@needs_ast
@needs_corpus
def test_real_ast_yields_blocks_for_a_program_with_else_branches():
    from cobol_transformer.testgen.cfg import load_program, manifest_for

    manifest = manifest_for(load_program(TRANSFORMED, "lgtestp4"))
    kinds = {b.kind for b in manifest.blocks}
    assert {"section", "paragraph", "if-then", "if-else"} <= kinds
    # Every probe must sit inside the source, and branch probes must not point
    # at the IF keyword itself.
    for block in manifest.blocks:
        assert 0 < block.probe_offset < 10 ** 7
        assert block.line_end >= block.line_start


@needs_cobc
@needs_ast
@needs_corpus
def test_oracle_then_checked_round_trip_on_a_real_program(tmp_path):
    """The full loop: instrument, run for truth, re-instrument, verify."""
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
    from cobol_transformer.testgen.cfg import load_program, manifest_for
    from cobol_transformer.testgen.oracle_runner import bless
    from cobol_transformer.testgen.run_and_report import run_testcase

    sources = load_program(TRANSFORMED, "lgtestp1")
    manifest = manifest_for(sources)
    runner = GnuCobolRunner()

    case = Case(
        test_id="itest1", program="lgtestp1",
        initial_values={"EIBCALEN": "9999", "CA-RETURN-CODE": "70"},
        variables_to_check=["ERP1FLDO", "CA-RETURN-CODE"],
        path=str(tmp_path / "itest1.json"),
    )
    ok, detail = bless(case, sources, str(tmp_path / "oracle"), runner)
    assert ok, detail
    # The oracle supplies the truth; nothing upstream invented it.
    assert case.expected_values["CA-RETURN-CODE"] == "70"
    assert case.expected_values["ERP1FLDO"]

    report = run_testcase(
        case, sources, manifest, str(tmp_path / "checked"), runner
    )
    assert report["compile_ok"] and report["run_ok"], report.get("error")
    assert report["all_match"], report["variables"]
    assert report["coverage"]["blocks_hit"], "no coverage probe fired"
    # EIBCALEN > 0 must take the true branch and route to A-GAIN.
    assert "IF-0001-THEN" in report["coverage"]["blocks_hit"]
    assert "PARA-A-GAIN" in report["coverage"]["blocks_hit"]


@needs_cobc
@needs_ast
@needs_corpus
def test_a_wrong_expected_value_is_reported_as_a_mismatch(tmp_path):
    """The check must be able to fail -- a suite that cannot fail proves nothing."""
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
    from cobol_transformer.testgen.cfg import load_program, manifest_for
    from cobol_transformer.testgen.run_and_report import run_testcase

    sources = load_program(TRANSFORMED, "lgtestp1")
    case = Case(
        test_id="itest2", program="lgtestp1",
        initial_values={"CA-RETURN-CODE": "70"},
        variables_to_check=["CA-RETURN-CODE"],
        expected_values={"CA-RETURN-CODE": "42"},      # deliberately wrong
        path=str(tmp_path / "itest2.json"),
    )
    report = run_testcase(
        case, sources, manifest_for(sources), str(tmp_path / "checked"),
        GnuCobolRunner(),
    )
    assert report["compile_ok"] and report["run_ok"], report.get("error")
    assert report["all_match"] is False
    assert report["variables"]["CA-RETURN-CODE"]["actual"] == "70"


@needs_cobc
@needs_ast
@needs_corpus
def test_every_transformed_program_instruments_and_compiles(tmp_path):
    """Instrumentation must not break any program in the corpus."""
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
    from cobol_transformer.testgen.cfg import load_program, manifest_for
    from cobol_transformer.testgen.instrumenter import instrument

    runner = GnuCobolRunner()
    programs = sorted(
        os.path.splitext(f)[0] for f in os.listdir(TRANSFORMED)
        if f.endswith(".cbl")
    )
    assert programs
    failures = []
    for program in programs:
        sources = load_program(TRANSFORMED, program)
        manifest = manifest_for(sources)
        case = Case(test_id="smoke", program=program, variables_to_check=[])
        result = instrument(
            sources.text, case, sources.symbols, mode="checked", manifest=manifest
        )
        # Only newly introduced code lines matter.  The corpus already
        # contains over-long *comment* banners from the transformation
        # pipeline, and columns 73+ are the ignored identification area.
        from cobol_transformer.linetools import is_comment_line

        original = set(sources.text.split("\n"))
        over = [
            ln for ln in result.text.split("\n")
            if len(ln) > CODE_END and not is_comment_line(ln) and ln not in original
        ]
        assert not over, f"{program}: generated lines past column 72: {over[:3]}"
        path = os.path.join(str(tmp_path), f"{program}.cbl")
        result.write(path)
        compiled = runner.compile(path, os.path.splitext(path)[0])
        if not compiled.ok:
            failures.append(f"{program}: {(compiled.stderr or '')[:300]}")
    assert not failures, "instrumented sources failed to compile:\n" + "\n".join(
        failures
    )


@needs_cobc
@pytest.mark.parametrize("flag,expect_hit,expect_miss,name", [
    # W-FLAG > 0 routes to SECOND-PARA, where 5 takes the THEN branch...
    ("5", "IF-0002-THEN", "IF-0002-ELSE", "five"),
    # ...and any other positive value takes the ELSE branch.
    ("1", "IF-0002-ELSE", "IF-0002-THEN", "other"),
])
def test_if_else_branch_probes_fire_on_the_branch_actually_taken(
    tmp_path, flag, expect_hit, expect_miss, name
):
    """Runtime proof that both sides of an IF/ELSE are instrumented correctly.

    Compiling is not enough: a probe that wrongly terminated the IF sentence
    would still compile, and would report *both* branches as hit.
    """
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
    from cobol_transformer.testgen.run_and_report import parse_checks, parse_coverage

    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    result = instrument(
        PROGRAM,
        Case(test_id="branch", program="DEMO",
             initial_values={"W-FLAG": flag},
             variables_to_check=["W-NAME"],
             expected_values={"W-NAME": name}),
        _symbols(), mode="checked", manifest=manifest,
    )
    source = str(tmp_path / "demo.cbl")
    result.write(source)

    runner = GnuCobolRunner()
    binary = str(tmp_path / "demo")
    compiled = runner.compile(source, binary)
    assert compiled.ok, compiled.stderr or compiled.stdout
    ran = runner.run(binary)
    assert ran.ok, ran.stderr

    hit = parse_coverage(ran.stdout)
    assert expect_hit in hit
    assert expect_miss not in hit, (
        "both branches reported as hit: the probe terminated the IF sentence"
    )
    assert "IF-0001-THEN" in hit          # W-FLAG > 0 is true for both cases
    assert parse_checks(ran.stdout)["W-NAME"][0] is True


@needs_cobc
def test_a_false_condition_fires_no_branch_probe(tmp_path):
    """With W-FLAG = 0 the guarded GO TO must not run, nor its probe."""
    from cobol_transformer.gnucobol.gnucobol_runner import GnuCobolRunner
    from cobol_transformer.testgen.run_and_report import parse_coverage

    manifest = cfg.build_manifest(PROGRAM, _demo_document(), "DEMO")
    result = instrument(
        PROGRAM,
        Case(test_id="false", program="DEMO", initial_values={"W-FLAG": "0"},
             variables_to_check=["W-NAME"], expected_values={"W-NAME": "other"}),
        _symbols(), mode="checked", manifest=manifest,
    )
    source = str(tmp_path / "demo0.cbl")
    result.write(source)
    runner = GnuCobolRunner()
    binary = str(tmp_path / "demo0")
    compiled = runner.compile(source, binary)
    assert compiled.ok, compiled.stderr or compiled.stdout
    ran = runner.run(binary)
    assert ran.ok, ran.stderr
    hit = parse_coverage(ran.stdout)
    assert "IF-0001-THEN" not in hit
    # Falling past the guarded GO TO still reaches SECOND-PARA's ELSE branch.
    assert "PARA-SECOND-PARA" in hit and "IF-0002-ELSE" in hit


# -- the per-program test-case floor --------------------------------------

def test_prompt_defaults_to_fifteen_and_states_the_floor():
    from cobol_transformer.testgen.prompt_builder import (
        DEFAULT_MIN_TESTS, build_prompt,
    )

    assert DEFAULT_MIN_TESTS == 15
    prompt = build_prompt(build_context(PROGRAM, "DEMO"), PROGRAM, "out/DEMO")
    assert "at least 15 test cases" in prompt
    assert "AT LEAST 15 test cases" in prompt
    assert "test15.json" in prompt
    # The floor must not read as a ceiling anywhere.
    assert "at most" not in prompt


def test_prompt_floor_is_overridable():
    from cobol_transformer.testgen.prompt_builder import build_prompt

    prompt = build_prompt(
        build_context(PROGRAM, "DEMO"), PROGRAM, "out/DEMO", min_tests=3
    )
    assert "at least 3 test cases" in prompt
    assert "test3.json" in prompt


def _fake_claude(monkeypatch, out_dir, count):
    """Stand in for the claude CLI, writing ``count`` valid test cases."""
    from cobol_transformer.testgen import generate_testcases as gt

    def fake_run(cmd, **kwargs):
        # The prompt must arrive on stdin.  As an argv element it exceeds the
        # Windows 32767-character command-line limit and dies with WinError 206.
        assert "input" in kwargs and kwargs["input"], "prompt was not sent on stdin"
        assert all(len(part) < 4096 for part in cmd), "prompt was passed in argv"
        os.makedirs(out_dir, exist_ok=True)
        for i in range(1, count + 1):
            with open(os.path.join(out_dir, f"test{i}.json"), "w") as fh:
                json.dump({
                    "test_id": f"test{i}", "program": "lgtestp1",
                    "description": "generated",
                    "initial_values": {"EIBCALEN": str(i)},
                    "variables_to_check": ["ERP1FLDO"],
                }, fh)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(gt.subprocess, "run", fake_run)


@needs_corpus
def test_generation_reports_a_shortfall_against_the_floor(monkeypatch, tmp_path):
    """Asking for 15 is not enough; a short run has to be reported as failing."""
    from cobol_transformer.testgen.generate_testcases import generate_for_program

    out_dir = os.path.join(str(tmp_path), "lgtestp1")
    _fake_claude(monkeypatch, out_dir, count=9)
    count, problems = generate_for_program(
        "lgtestp1", TRANSFORMED, str(tmp_path), "claude", 15, 60,
    )
    assert count == 9
    assert any("9 test case(s) written, 15 required" in p for p in problems)


@needs_corpus
def test_generation_accepts_a_run_that_meets_the_floor(monkeypatch, tmp_path):
    from cobol_transformer.testgen.generate_testcases import generate_for_program

    out_dir = os.path.join(str(tmp_path), "lgtestp1")
    _fake_claude(monkeypatch, out_dir, count=15)
    count, problems = generate_for_program(
        "lgtestp1", TRANSFORMED, str(tmp_path), "claude", 15, 60,
    )
    assert count == 15
    assert problems == []


# -- regressions found by running the corpus ------------------------------

def test_blank_numeric_field_is_refused_not_asserted_as_zero():
    """A numeric field that DISPLAYs blank was never initialised.

    Asserting ``= 0`` against it produces a check that fails against the very
    run the value was captured from (lgapdb01's CA-POLICY-NUM, PIC 9(10)).
    """
    blank = parse_picture("9(10)")
    with pytest.raises(LiteralError):
        pic_info_to_condition_literal(blank, "          ")
    assert unsupported_reason(blank, "   ") is not None
    # The MOVE form keeps treating an empty operand as zero: there it is an
    # instruction to the field, not an observation of it.
    assert pic_info_to_move_literal(blank, "") == "0"


def test_numeric_edited_length_counts_columns_not_digits():
    """PIC +9(5) occupies six columns and DISPLAYs as '+00100'.

    ``parse_picture`` reports length 5 for it (a digit count), so enforcing
    that as a character width rejected lgicdb01's own EM-SQLRC values.
    """
    edited = parse_picture("+9(5)")
    assert pic_info_to_condition_literal(edited, "+00100") == "'+00100'"
    assert pic_info_to_condition_literal(edited, "-99999") == "'-99999'"
    assert unsupported_reason(edited, "+00100") is None
