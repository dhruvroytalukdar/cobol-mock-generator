"""Evidence that the lexical detector is a faithful stand-in for the AST.

The fallback path exists because the language server refuses to emit an AST for
programs whose CICS commands its validator dislikes (``SEND TEXT ... WAIT``
without ``TERMINAL``, for instance).  Falling back is only defensible if both
paths find the same constructs, so that is asserted here against the real
corpus: for every program the AST backend *can* parse, the anchored EXEC spans
must equal the lexer's spans exactly.

Requires Java 21, the Z Open Editor extension and a running AST server; skipped
otherwise.
"""
import glob
import os

import pytest

from cobol_transformer.analysis.anchor import anchor_nodes
from cobol_transformer.analysis.node_classifier import Category, NodeClassifier
from cobol_transformer.analysis.text_detector import detect_by_text
from cobol_transformer.ast_client.ast_model import normalize_newlines
from cobol_transformer.ast_client.http_client import AstClientConfig, HttpAstClient
from cobol_transformer.discovery.copybook_resolver import CopybookResolver
from cobol_transformer.errors import AstUnavailableError
from cobol_transformer.inline.inliner import Inliner

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "genapp-files", "src")

_client = HttpAstClient(AstClientConfig())
needs_ast = pytest.mark.skipif(
    not _client.available(), reason="AST server not running on 127.0.0.1:4010"
)

EXEC_CATEGORIES = (Category.CICS, Category.SQL, Category.EXEC_UNKNOWN)


def _expanded(path):
    resolver = CopybookResolver([SRC], source_dir=SRC)
    return normalize_newlines(
        Inliner(resolver, continue_on_missing=True).inline_file(path).text
    )


@needs_ast
@pytest.mark.parametrize(
    "path", sorted(glob.glob(os.path.join(SRC, "*.cbl"))),
    ids=lambda p: os.path.basename(p)[:-4],
)
def test_ast_and_lexer_find_identical_exec_spans(path):
    text = _expanded(path)
    try:
        document = _client.get_ast(text, os.path.basename(path))
    except AstUnavailableError:
        pytest.skip("language server declined to parse this program")

    ast_res = anchor_nodes(text, document, NodeClassifier())
    assert ast_res.skipped == 0, "every classified node must anchor"

    ast_spans = sorted(
        (r.start, r.end) for r in ast_res.ranges if r.category in EXEC_CATEGORIES
    )
    text_spans = sorted(
        (r.start, r.end)
        for r in detect_by_text(text).ranges
        if r.category in EXEC_CATEGORIES
    )
    assert ast_spans == text_spans
