"""Test-case generation, instrumentation and coverage for transformed programs.

Consumes the self-contained GnuCOBOL programs produced by the transformation
pipeline and adds, as strictly additive tooling:

* :mod:`variable_context` -- grounding facts about a program's variables,
* :mod:`cfg` -- the ground-truth paragraph/section and IF/ELSE block inventory,
* :mod:`instrumenter` -- oracle-mode and checked-mode instrumented sources,
* :mod:`oracle_runner` -- freezes real expected values into a test case,
* :mod:`run_and_report` -- the repeatable regression + coverage run.

Nothing here modifies the transformation pipeline itself.
"""
