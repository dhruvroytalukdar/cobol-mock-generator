"""Build the test-generation prompt for one transformed program.

The prompt is built around one hard rule: **the model picks inputs, never
outcomes.**  It chooses initial values and which variables are worth checking;
a real execution supplies what those variables end up holding.  Asking for
expected values would invite a plausible guess at the result of mock
substitution rules that cannot be traced by hand, and a wrong golden is worse
than no golden -- it makes a broken suite report success.

Everything the model is allowed to name is given to it explicitly: the full
program text, the variable inventory from :mod:`variable_context` with each
field's PICTURE, and the paragraph skeleton.  Inventing a name or a
type-incompatible value is therefore always avoidable, and the instrumenter
rejects it when it happens anyway.
"""
from __future__ import annotations

from typing import List, Optional

from .variable_context import ProgramContext, VariableFact

#: A compact one-line-per-field table beats indented JSON here: a real program
#: carries hundreds of map fields, and the pretty form costs several times the
#: tokens for no extra information.
_VARIABLE_HEADER = (
    "NAME | PIC | CATEGORY | LEN | DEC | SIGNED | SECTION | DEFAULT VALUE"
)


def _variable_line(v: VariableFact) -> str:
    return (
        f"{v.name} | {v.pic_text} | {v.category} | {v.length} | {v.decimals} | "
        f"{'yes' if v.signed else 'no'} | {v.section} | "
        f"{v.default_value if v.default_value is not None else '-'}"
    )


#: Test cases to require per program.  A floor rather than a ceiling: coverage
#: of a program's reachable decision points is usually satisfied by far fewer,
#: so the remainder is spent on boundary and equivalence-class variation, which
#: is where a regression suite earns its keep.
DEFAULT_MIN_TESTS = 15


def build_prompt(
    context: ProgramContext,
    source_text: str,
    out_dir: str,
    min_tests: int = DEFAULT_MIN_TESTS,
) -> str:
    """Return the full headless prompt for ``context``'s program."""
    variables = "\n".join(_variable_line(v) for v in context.variables)
    paragraphs = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(context.paragraphs))
    program = context.program

    return f"""You are generating black-box test cases for a COBOL program that has
already been made locally runnable. The program takes no command-line arguments
and no stdin -- its entire behaviour is determined by the initial values of its
WORKING-STORAGE variables (including synthesized EIB and commarea fields),
because every external CICS/SQL call has been replaced with a deterministic
mock.

Your job has two parts:

1. Pick a diverse set of initial values for the variables that influence
   control flow: IF conditions, EVALUATE subjects, loop conditions, and GO TO
   routing fields such as EIBCALEN or a CA-RETURN-CODE-style field.
2. Pick which variables are worth checking at the end of the run -- output
   fields, computed totals, status/return-code fields, error-message fields --
   whose final value meaningfully reflects that the intended path ran.

Do NOT attempt to compute or guess the final values of the variables you choose
to check. You do not have a COBOL interpreter and cannot reliably trace the
mock substitution rules by hand. A separate deterministic step executes the real
program and captures the actual final values. Your only job is to pick *which*
variables are worth checking, never what their values will be. Do not include an
"expected_values" key.

You will produce **at least {min_tests} test cases** for this ONE program,
because a single test case can only exercise one path. Your goal, across all the
test cases TOGETHER, is to maximise line and branch coverage: every
paragraph/section should be entered by at least one test, and every IF/ELSE
branch you can identify should be taken in both directions by at least one test.

Reaching every decision point you can control will usually take fewer than
{min_tests} cases. Write the rest anyway, and spend them on variation that could
plausibly break something rather than on padding: the boundary on each side of
every numeric comparison, the empty/SPACES/zero form of each field a condition
reads, the longest value a field can hold, and a representative from each
distinct equivalence class of a field that is compared against several
literals. Do not submit near-duplicate cases that differ only in a value no
condition in this program ever reads.

## Something specific to these mocked programs

A mocked statement often *overwrites* fields right after the program starts.
For example a mocked `RECEIVE MAP` assigns fixed dummy values to every input
field of the map. If a decision later reads a field that a mock has already
overwritten, no initial value you choose can change that decision -- and where
a BMS output record REDEFINES the input record, writing the "O" field is
undone by the mock writing the "I" field over the same bytes.

When you find a decision point like that, say so in the description of a test
case that gets as close to it as possible, and move on. Do not invent initial
values for a condition you cannot actually influence.

## Program source: {program}

```cobol
{source_text}
```

## Available variables -- choose ONLY from this list, do not invent names

{_VARIABLE_HEADER}
{variables}

## Program structure (paragraph/section names, in order)

{paragraphs}

## Instructions

1. Read the program and identify every decision point: each IF (noting whether
   it has an ELSE), each EVALUATE and its WHEN clauses, each PERFORM
   UNTIL/VARYING/TIMES loop, and each GO TO-based routing decision.
2. Write AT LEAST {min_tests} test cases. Cover first: every decision point you
   found, exercised in as many distinct outcomes as you can drive purely by
   choosing initial WORKING-STORAGE values, including both the true and false
   side of every IF that has an ELSE. If a decision depends on a field you
   cannot control (see the section above), note that in a description and skip
   it rather than guessing. Then keep going until you have {min_tests}, using
   the boundary and equivalence-class variation described above.
3. Include boundary and edge-case values wherever a condition in the source
   suggests one (a field compared with `> 0`, with `= SPACES`, or with a
   specific literal) -- not only "typical" values.
4. Give each test case a one-sentence `description` naming the decision
   point(s) or path it is meant to exercise.
5. Give each test case one or more `variables_to_check` whose final value would
   visibly differ depending on whether that decision point took the intended
   path -- for instance an error-message field that only one branch sets.
6. Use only value shapes that are legal for the variable's PIC clause as listed
   above: the right length, numeric versus alphanumeric, and a sign only where
   the PICTURE has an S. Values are written as JSON strings either way
   (`"70"`, `"-5"`, `"Customer does not exist"`).

## Output

Write one file per test case to `{out_dir}/test<N>.json`, numbered from 1 with
no gaps: test1.json, test2.json, ... through at least test{min_tests}.json.
Each is shaped exactly as:

{{
  "test_id": "test<N>",
  "program": "{program}",
  "description": "<one sentence>",
  "initial_values": {{"<VAR>": "<value>"}},
  "variables_to_check": ["<VAR>"]
}}

Write only those JSON files. Do not modify the COBOL source, and do not create
any other file.
"""


def write_prompt(path: str, prompt: str) -> str:
    import os

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(prompt)
    return path
