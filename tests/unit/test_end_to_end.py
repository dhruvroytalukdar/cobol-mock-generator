"""End-to-end properties of the transformation on the real corpus.

The central guarantee is checked here: reversing the transformation must
reproduce the input exactly, which means nothing outside a mocked construct
was altered.  These run without Java (the pipeline falls back to the lexical
detector) but do need the corpus.
"""
import glob
import os

import pytest

from cobol_transformer.pipeline import PipelineOptions, run
from cobol_transformer.verify import verify

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "genapp-files", "src")
PROGRAMS = sorted(glob.glob(os.path.join(SRC, "*.cbl")))

pytestmark = pytest.mark.skipif(not PROGRAMS, reason="GenApp corpus not present")

# No AST server is required: detection falls back to the lexical scanner, whose
# parity with the AST is asserted separately in test_detector_parity.py.
OPTS = PipelineOptions(use_ast=False)


@pytest.fixture(scope="module")
def transformed():
    return {os.path.basename(p)[:-4]: run(p, OPTS) for p in PROGRAMS}


@pytest.mark.parametrize("name", [os.path.basename(p)[:-4] for p in PROGRAMS])
def test_only_mocked_constructs_differ(transformed, name):
    res = transformed[name]
    v = verify(res.expanded_text, res.output_text, res.manifest)
    assert v.ok, "\n".join(v.differences)


@pytest.mark.parametrize("name", [os.path.basename(p)[:-4] for p in PROGRAMS])
def test_every_construct_is_handled(transformed, name):
    m = transformed[name].manifest
    assert m.skipped_count == 0
    assert m.constructs, "each program contains CICS or SQL to mock"


@pytest.mark.parametrize("name", [os.path.basename(p)[:-4] for p in PROGRAMS])
def test_original_statements_remain_visible(transformed, name):
    """Every mocked statement is still readable in the output, as a comment."""
    res = transformed[name]
    lines = res.output_text.split("\n")
    for c in res.manifest.constructs:
        if c.status != "commented_and_mocked":
            continue
        for ln in range(c.commented_line_start - 1, c.commented_line_end):
            line = lines[ln]
            if not line.strip():
                continue  # blank lines are already inert and left as they were
            assert line[6] == "*", f"{name}: line {ln + 1} not commented"


@pytest.mark.parametrize("name", [os.path.basename(p)[:-4] for p in PROGRAMS])
def test_generated_lines_respect_the_code_area(transformed, name):
    res = transformed[name]
    for c in res.manifest.constructs:
        for line in c.generated_text:
            assert len(line) <= 72, f"{name}: generated line exceeds column 72"


def test_transformation_is_deterministic():
    """The same input must always produce byte-identical output."""
    path = PROGRAMS[0]
    assert run(path, OPTS).output_text == run(path, OPTS).output_text
