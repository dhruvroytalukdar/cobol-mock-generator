"""Anchoring, EXEC option parsing, PICTURE handling and the symbol table."""
from cobol_transformer.analysis.anchor import anchor_nodes
from cobol_transformer.analysis.exec_text_parser import (
    literal_of, parse_exec, split_arg_identifier,
)
from cobol_transformer.analysis.node_classifier import Category
from cobol_transformer.analysis.pic_parser import PicCategory, parse_picture
from cobol_transformer.analysis.symbol_table import build_symbol_table
from cobol_transformer.ast_client.ast_model import AstDocument, AstNode


def _doc(*nodes: AstNode) -> AstDocument:
    root = AstNode("CompilationUnit", "", {}, list(nodes))
    return AstDocument(root)


def _exec_node(text: str, dialect: str = "CICS") -> AstNode:
    return AstNode("ExecEndExec", text, {"_SqlOrCics": dialect}, [])


# -- anchoring -------------------------------------------------------------

def test_duplicate_statements_anchor_to_distinct_occurrences():
    a = "EXEC CICS ABEND END-EXEC"
    text = f"       {a}\n       MOVE 1 TO X\n       {a}\n"
    res = anchor_nodes(text, _doc(_exec_node(a), _exec_node(a)))
    assert len(res.ranges) == 2
    assert res.ranges[0].start < res.ranges[1].start
    assert res.ranges[0].start == text.index(a)
    assert res.ranges[1].start == text.rindex(a)


def test_missing_source_text_fails_closed():
    text = "       MOVE 1 TO X\n"
    res = anchor_nodes(text, _doc(_exec_node("EXEC CICS NOPE END-EXEC")))
    assert res.ranges == []
    assert res.skipped == 1
    assert res.diagnostics[0].code == "E-ANCHOR-NOT-FOUND"


def test_out_of_order_node_is_reported_distinctly():
    a = "EXEC CICS ABEND END-EXEC"
    b = "EXEC CICS RETURN END-EXEC"
    text = f"       {a}\n       {b}\n"
    # b then a: the second lookup can only find a *before* the cursor.
    res = anchor_nodes(text, _doc(_exec_node(b), _exec_node(a)))
    assert res.skipped == 1
    assert res.diagnostics[0].code == "E-ANCHOR-OUT-OF-ORDER"


def test_crlf_in_source_text_still_anchors():
    text = "       EXEC CICS READ\n            INTO(X)\n       END-EXEC\n"
    needle = "EXEC CICS READ\r\n            INTO(X)\r\n       END-EXEC"
    res = anchor_nodes(text, _doc(_exec_node(needle)))
    assert len(res.ranges) == 1


def test_exec_children_are_pruned_not_double_matched():
    inner = _exec_node("EXEC CICS ABEND END-EXEC")
    inner.children = [_exec_node("EXEC CICS ABEND END-EXEC")]
    text = "       EXEC CICS ABEND END-EXEC\n"
    res = anchor_nodes(text, _doc(inner))
    assert len(res.ranges) == 1


# -- CICS option parsing ---------------------------------------------------

def test_cics_options_and_flags():
    cmd = parse_exec(
        "READ FILE('KSDSCUST') INTO(WS-REC) RIDFLD(WS-KEY) RESP(WS-RESP) UPDATE",
        "CICS",
    )
    assert cmd.verb == "READ"
    assert literal_of(cmd.option("FILE")) == "KSDSCUST"
    assert cmd.option("INTO") == "WS-REC"
    assert cmd.has_flag("UPDATE")
    assert cmd.parse_ok


def test_two_word_verb_with_argument_keeps_the_option():
    cmd = parse_exec("Get Counter(GENAcount) Pool(GENApool) Value(WS-V)", "CICS")
    assert cmd.verb == "GET COUNTER"
    assert cmd.option("COUNTER") == "GENAcount"
    assert cmd.option("VALUE") == "WS-V"
    assert cmd.parse_ok


def test_two_word_verb_without_argument_is_consumed():
    cmd = parse_exec("WRITEQ TS QUEUE(Q) FROM(REC)", "CICS")
    assert cmd.verb == "WRITEQ TS"
    assert cmd.option("QUEUE") == "Q"


def test_parenthesis_inside_literal_does_not_break_parsing():
    cmd = parse_exec("ABEND ABCODE('A(B') NODUMP", "CICS")
    assert literal_of(cmd.option("ABCODE")) == "A(B"
    assert cmd.has_flag("NODUMP")


def test_split_arg_identifier_rejects_literals_and_expressions():
    assert split_arg_identifier("WS-REC") == "WS-REC"
    assert split_arg_identifier("'KSDSCUST'") is None
    assert split_arg_identifier("WS-A + 1") is None


# -- SQL parsing -----------------------------------------------------------

def test_sql_select_into_and_table():
    cmd = parse_exec(
        "SELECT NAME, DOB INTO :WS-NAME, :WS-DOB FROM CUSTOMER WHERE ID = :WS-ID",
        "SQL",
    )
    assert cmd.verb == "SELECT"
    assert cmd.options["_TABLE"] == "CUSTOMER"
    assert cmd.options["_INTO"] == "WS-NAME,WS-DOB"


def test_declare_cursor_with_attributes_between_name_and_cursor():
    cmd = parse_exec("DECLARE Cust_Cursor Insensitive Scroll Cursor For SELECT A", "SQL")
    assert cmd.verb == "DECLARE CURSOR"
    assert cmd.options["CURSOR"] == "Cust_Cursor"


# -- PICTURE ---------------------------------------------------------------

def test_picture_categories():
    assert parse_picture("X(20)").category is PicCategory.ALPHANUMERIC
    assert parse_picture("X(20)").length == 20
    p = parse_picture("S9(4)V99 COMP")
    assert p.category is PicCategory.NUMERIC
    assert p.digits == 4 and p.decimals == 2 and p.signed


# -- symbol table ----------------------------------------------------------

SRC = """\
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP        PIC S9(8) COMP.
       01  WS-GROUP.
         03 WS-A          PIC X(10).
         03 WS-B          PIC 9(4).
       01  WS-ALT REDEFINES WS-GROUP.
         03 WS-C          PIC X(14).
       LINKAGE SECTION.
       01  DFHCOMMAREA.
         02 CA-REQ        PIC X(6).
       PROCEDURE DIVISION.
"""


def test_symbol_table_levels_sections_and_groups():
    st = build_symbol_table(SRC)
    assert st.get("WS-RESP").section == "WORKING-STORAGE"
    assert st.get("CA-REQ").section == "LINKAGE"
    assert st.get("WS-GROUP").children == ["WS-A", "WS-B"]
    assert st.get("WS-ALT").redefines == "WS-GROUP"


def test_elementary_fields_skip_redefines_siblings():
    st = build_symbol_table(SRC)
    names = [s.name for s in st.elementary_fields("WS-GROUP")]
    assert names == ["WS-A", "WS-B"]
    assert "WS-C" not in names
