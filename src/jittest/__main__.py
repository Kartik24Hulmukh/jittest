"""Allow ``python -m jittest`` as an equivalent of the ``jittest`` console script.

The console script only exists after ``pip install``; ``python -m jittest``
works from a checkout with ``PYTHONPATH=src`` and from environments whose
scripts directory is not on ``PATH``. Both routes share ``cli.main`` so exit
codes and refusal semantics are identical.
"""
from __future__ import annotations

import sys

from jittest.cli import main

if __name__ == "__main__":
    sys.exit(main())
