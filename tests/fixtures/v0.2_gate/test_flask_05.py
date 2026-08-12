import sqlite3
import sys
from pathlib import Path


def test_converter():
    if "timestamp" in sqlite3.converters:
        del sqlite3.converters["timestamp"]
    if "TIMESTAMP" in sqlite3.converters:
        del sqlite3.converters["TIMESTAMP"]
    sys.path.insert(0, str(Path("examples/tutorial").resolve()))
    import flaskr.db  # noqa: F401
    assert "timestamp" in sqlite3.converters or "TIMESTAMP" in sqlite3.converters
