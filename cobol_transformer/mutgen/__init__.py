"""Mutation-intent test-suite degradation, built on top of :mod:`testgen`.

Given a transformed program ``P`` and its frozen test suite ``T`` (from
``testsuites/<program>``), this package evaluates hand-authored mutant
sources ``P'``/``P''`` against the *same, unchanged* ``T`` and reports which
test cases fail.

It reuses :mod:`testgen.run_and_report` and the rest of the testgen pipeline
completely unmodified -- a mutant is evaluated by copying it into an isolated
workspace that looks like a ``transformed/`` + ``testsuites/`` pair, and
running the existing checked-mode instrument/compile/run/compare flow against
it. Nothing here touches ``testgen/``, ``transformed/``, or ``testsuites/``.
"""
