"""Lexical masking, EXEC discovery and COPY/INCLUDE scanning."""
from cobol_transformer.inline.lexer import Kind, SourceLexer
from cobol_transformer.inline.scanner import scan_copy_statements


def fixed(*lines: str) -> str:
    """Build fixed-format source from Area-B statement text."""
    return "\n".join("       " + l if not l.startswith("      *") else l
                     for l in lines) + "\n"


def test_comment_lines_are_masked():
    src = fixed("      * COPY LGCMAREA.", "MOVE 1 TO A.")
    lx = SourceLexer(src)
    assert lx.kind_at(src.index("COPY")) == Kind.COMMENT
    assert scan_copy_statements(src) == []


def test_copy_inside_string_literal_is_not_a_statement():
    src = fixed("MOVE 'COPY LGCMAREA.' TO WS-TEXT.")
    lx = SourceLexer(src)
    assert lx.kind_at(src.index("COPY")) == Kind.STRING
    assert scan_copy_statements(src) == []


def test_real_copy_statement_is_found():
    src = fixed("COPY LGCMAREA.")
    found = scan_copy_statements(src)
    assert len(found) == 1
    assert found[0].name == "LGCMAREA"
    assert found[0].form == "COPY"


def test_copy_of_library_is_captured():
    src = fixed("COPY MYBOOK OF MYLIB.")
    found = scan_copy_statements(src)
    assert found[0].name == "MYBOOK"
    assert found[0].library == "MYLIB"


def test_exec_sql_include_is_treated_as_copy():
    src = fixed("EXEC SQL", "  INCLUDE SQLCA", "END-EXEC.")
    found = scan_copy_statements(src)
    assert len(found) == 1
    assert found[0].name == "SQLCA"
    assert found[0].form == "EXEC_SQL_INCLUDE"


def test_multiline_exec_block_boundaries():
    src = fixed(
        "EXEC CICS READ FILE('KSDSCUST')",
        "     INTO(WS-REC)",
        "END-EXEC.",
    )
    lx = SourceLexer(src)
    assert len(lx.exec_blocks) == 1
    blk = lx.exec_blocks[0]
    assert blk.dialect == "CICS"
    assert blk.text.startswith("EXEC CICS READ")
    assert blk.text.endswith("END-EXEC")


def test_two_adjacent_exec_blocks_are_separate():
    src = fixed(
        "EXEC CICS ABEND ABCODE('LGV1') END-EXEC",
        "EXEC CICS ABEND ABCODE('LGV1') END-EXEC",
    )
    lx = SourceLexer(src)
    assert len(lx.exec_blocks) == 2
    assert lx.exec_blocks[0].start != lx.exec_blocks[1].start


def test_end_exec_does_not_open_a_block():
    src = fixed("EXEC CICS RETURN END-EXEC.", "MOVE 1 TO A.")
    lx = SourceLexer(src)
    assert len(lx.exec_blocks) == 1
