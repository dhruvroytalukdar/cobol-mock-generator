"""LLM-judge experiment: OBSOLETE vs BUG_TRIGGERED classification of failing tests.

Consumes the artifacts produced by :mod:`mutgen` (``modification_quantity/``)
and never modifies them. Nothing here touches the transformation pipeline,
testgen, or mutgen.

* :mod:`ground_truth` -- derives the OBSOLETE/BUG_TRIGGERED label for every
  failing test straight from ``mutation_runs/<program>/results.json``.
* :mod:`prepare_case` -- builds one self-contained, read-only sandbox per
  (variant, program, label) for the judge agent to work in.
* :mod:`tools_server` -- the MCP server exposing read_file/write_file/
  get_failing_testcases/get_coverage, scoped to one sandbox.
* :mod:`backends` -- swappable agent runtimes (claude CLI, or any LiteLLM
  model) behind one interface.
* :mod:`run_judge` -- CLI entry point tying prepare_case + tools_server +
  a backend together for one run.
* :mod:`score` -- compares a run's verdicts.json against ground_truth.
"""
