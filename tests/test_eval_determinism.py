"""Target extraction and risk ranking are deterministic. Defect 70.

An evaluation run reported a completion rate that fell from 40% to 4.7% to 0%
across re-runs of the *same* bugs, and the degradation was attributed to
"session-dependent" behaviour in ``extract_targets()`` and ``rank()`` causing
changed symbols to intermittently fall below the 0.35 risk threshold.

That is a load-bearing claim: if it were true, no catch rate this project ever
publishes could be reproduced, and the correct response would be to stop
measuring and rewrite the scorer. So it must not remain a plausible story. This
module exists to make it mechanically falsifiable.

The scoring path contains no set iteration, no ``hash()`` dependence, no clock,
no filesystem read and no randomness. ``score_target()`` is a pure function of
the target's own text, and ``rank()`` sorts on ``(-score, qualified)`` -- a
total order whose tiebreak is a unique string, so equal scores cannot reorder.
These tests assert that directly, including under shuffled input order, which
is the only channel through which an unstable sort could leak.

If these tests pass and a completion rate still varies between runs, the
variance is a statement about the *inputs* -- the repository state the harness
hands to the scorer -- and not about the scorer. That is where the real defect
was: see ``eval/run_bugsinpy.py::ensure_repo``.
"""
from __future__ import annotations

import random
import unittest

from jittest.diff import ChangeTarget, _innermost, enclosing_symbols
from jittest.risk import rank, score_target

REPEATS = 64

SOURCE = '''
import os


class Ledger:
    """Something in the consequential domain, to exercise that signal."""

    def settle(self, amounts):
        total = 0
        for amount in amounts:
            if amount < 0:
                raise ValueError("negative")
            total += amount
        return round(total / max(1, len(amounts)), 2)

    def refund(self, invoice, amount):
        if amount > invoice.balance:
            return None
        invoice.balance -= amount
        return invoice.balance


def helper(values):
    return values[0:1]
'''


def _target(symbol: str, source: str, churn: int = 8,
            before: str = "x = 1") -> ChangeTarget:
    return ChangeTarget(
        file_path="src/pkg/module.py",
        symbol=symbol,
        start_line=1,
        end_line=1 + len(source.splitlines()),
        added_lines=list(range(1, churn + 1)),
        removed_lines=[],
        source_after=source,
        source_before=before,
    )


class ScoreTargetIsPure(unittest.TestCase):
    def test_repeated_scoring_is_byte_identical(self) -> None:
        target = _target("Ledger.settle", SOURCE)
        first = score_target(target)
        for _ in range(REPEATS):
            again = score_target(target)
            self.assertEqual(first.score, again.score)
            self.assertEqual(first.reasons, again.reasons)
            self.assertEqual(first.band, again.band)

    def test_equal_content_scores_equally(self) -> None:
        """Two targets differing only in name must score identically.

        If scoring ever depended on identity, memory address or insertion
        order, this is where it would show.
        """
        a = score_target(_target("alpha", SOURCE))
        b = score_target(_target("omega", SOURCE))
        self.assertEqual(a.score, b.score)
        self.assertEqual(a.reasons, b.reasons)


class RankIsOrderIndependent(unittest.TestCase):
    def _corpus(self) -> list[ChangeTarget]:
        return [
            _target("Ledger.settle", SOURCE, churn=20),
            _target("Ledger.refund", SOURCE, churn=14),
            _target("helper", "return values[0:1]", churn=1, before=""),
            # Deliberate score tie: identical bodies, different names. The
            # tiebreak is `qualified`, so the order must still be stable.
            _target("tie_a", SOURCE, churn=9),
            _target("tie_b", SOURCE, churn=9),
        ]

    def test_shuffled_input_gives_identical_output(self) -> None:
        baseline = [s.target.qualified for s in rank(self._corpus())]
        scores = [s.score for s in rank(self._corpus())]
        rng = random.Random(20260801)
        for _ in range(REPEATS):
            shuffled = self._corpus()
            rng.shuffle(shuffled)
            ranked = rank(shuffled)
            self.assertEqual([s.target.qualified for s in ranked], baseline)
            self.assertEqual([s.score for s in ranked], scores)

    def test_threshold_membership_is_stable(self) -> None:
        """The set of targets surviving the 0.35 gate must not move.

        This is the exact behaviour the non-determinism report described:
        symbols 'intermittently dropping below the risk threshold'.
        """
        corpus = self._corpus()
        expected = {s.target.qualified for s in rank(corpus, threshold=0.35)}
        for _ in range(REPEATS):
            got = {s.target.qualified for s in rank(corpus, threshold=0.35)}
            self.assertEqual(got, expected)

    def test_top_k_is_respected_and_stable(self) -> None:
        corpus = self._corpus()
        for k in (1, 2, 3):
            first = [s.target.qualified for s in rank(corpus, top_k=k)]
            self.assertLessEqual(len(first), k)
            for _ in range(8):
                self.assertEqual(
                    [s.target.qualified for s in rank(corpus, top_k=k)], first)


class SymbolResolutionIsStable(unittest.TestCase):
    def test_enclosing_symbols_is_repeatable(self) -> None:
        first = enclosing_symbols(SOURCE)
        self.assertTrue(first, "fixture should contain symbols")
        for _ in range(REPEATS):
            self.assertEqual(enclosing_symbols(SOURCE), first)

    def test_innermost_is_repeatable_for_every_line(self) -> None:
        symbols = enclosing_symbols(SOURCE)
        total = len(SOURCE.splitlines())
        baseline = [_innermost(symbols, n) for n in range(1, total + 1)]
        for _ in range(8):
            again = [_innermost(symbols, n) for n in range(1, total + 1)]
            self.assertEqual(again, baseline)

    def test_innermost_prefers_the_narrowest_covering_symbol(self) -> None:
        symbols = enclosing_symbols(SOURCE)
        method = next(s for s in symbols if s[0] == "Ledger.settle")
        hit = _innermost(symbols, method[1] + 1)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit[0], "Ledger.settle")


if __name__ == "__main__":
    unittest.main()
