"""jittest - just-in-time catching tests for pull requests.

The open-source reference implementation of Just-in-Time catching test
generation, the method published by Meta in 2026 (arXiv 2601.22832).

A catching test is not a test that passes. It is a test that PASSES on the
base commit and FAILS on the head commit, proving the change broke something.
That distinction is the whole product.
"""
from __future__ import annotations

__version__ = "0.3.5"
__all__ = ["__version__"]
