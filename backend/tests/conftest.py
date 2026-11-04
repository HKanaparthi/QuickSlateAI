"""
Test infrastructure: enforce OR-Tools constraints for all Phase 2 tests.

Two guarantees applied automatically via autouse:
  1. num_search_workers = 1  — single-threaded, reproducible, low-resource.
  2. Total solver time per test ≤ TEST_SOLVER_BUDGET_SECONDS (5 s) — cumulative
     across ALL CpSolver.Solve() calls within one test, including every stage
     of the lexicographic optimizer and every neighborhood-expansion attempt.
     The cap is per-test, not per individual Solve call.

Neither setting touches production solver defaults in solver.py or repair.py.
"""
import time
import pytest
from ortools.sat.python import cp_model

TEST_SOLVER_BUDGET_SECONDS = 5.0

_original_solve = cp_model.CpSolver.Solve


@pytest.fixture(autouse=True)
def limit_ortools_workers(monkeypatch):
    """
    Patch CpSolver.Solve for the duration of one test.

    The closure captures test_start so that each successive Solve call within
    the same test draws from the same 5-second pool.  The monkeypatch teardown
    restores the original after the test, leaving production code unaffected.
    """
    test_start = time.monotonic()

    def _capped_solve(self, model, solution_callback=None):
        elapsed = time.monotonic() - test_start
        remaining = max(0.001, TEST_SOLVER_BUDGET_SECONDS - elapsed)

        self.parameters.num_search_workers = 1

        # Respect whichever limit is tighter: what the caller already set,
        # or what remains in this test's 5-second pool.
        caller_max = self.parameters.max_time_in_seconds
        self.parameters.max_time_in_seconds = (
            min(caller_max, remaining) if caller_max > 0 else remaining
        )

        if solution_callback is not None:
            return _original_solve(self, model, solution_callback)
        return _original_solve(self, model)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", _capped_solve)
