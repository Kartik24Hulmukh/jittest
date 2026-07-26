"""The ledger: every candidate, every verdict, every human reaction.

This is the asset. The code in this repository can be reimplemented by a
competent engineer in a fortnight. A labelled corpus of real diffs, generated
candidates, mechanical oracle verdicts and what the human actually did next
cannot be reimplemented at all - it can only be accumulated, one pull request
at a time, starting the day the first person installs the Action.

Everything is local SQLite. Nothing leaves the machine. `export` is anonymised
by default so a maintainer can contribute outcome labels to the public corpus
without leaking source.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Candidate", "Ledger", "HUMAN_OUTCOMES"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    created          REAL NOT NULL,
    schema_version   INTEGER NOT NULL DEFAULT 2,
    repo             TEXT,
    pr               TEXT,
    base_rev         TEXT,
    head_rev         TEXT,
    file_path        TEXT,
    symbol           TEXT,
    risk_score       REAL,
    risk_reasons     TEXT,
    model            TEXT,
    attempt          INTEGER,
    test_hash        TEXT,
    test_code        TEXT,
    oracle_catching  INTEGER,
    oracle_reason    TEXT,
    latent           INTEGER DEFAULT 0,
    assess_verdict   TEXT,
    assess_conf      REAL,
    assess_summary   TEXT,
    reported         INTEGER DEFAULT 0,
    cost_usd         REAL DEFAULT 0,
    seconds          REAL DEFAULT 0,
    human_outcome    TEXT,
    human_note       TEXT,
    human_at         REAL
);
CREATE INDEX IF NOT EXISTS idx_candidates_repo ON candidates(repo);
CREATE INDEX IF NOT EXISTS idx_candidates_hash ON candidates(test_hash);
CREATE INDEX IF NOT EXISTS idx_candidates_outcome ON candidates(human_outcome);
"""

# What a human did after seeing the finding. These labels are the training
# signal for a learned risk model, and the only honest measure of precision.
HUMAN_OUTCOMES = (
    "fixed_code",        # the author changed the code: we were right
    "kept_test",         # the author merged the generated test
    "intended",          # the author says the new behaviour is deliberate
    "false_positive",    # the finding was wrong or useless
    "ignored",           # no reaction at all
)


@dataclass
class Candidate:
    repo: str = ""
    pr: str = ""
    base_rev: str = ""
    head_rev: str = ""
    file_path: str = ""
    symbol: str = ""
    risk_score: float = 0.0
    risk_reasons: list[str] = field(default_factory=list)
    model: str = ""
    attempt: int = 0
    test_code: str = ""
    oracle_catching: bool = False
    oracle_reason: str = ""
    latent: bool = False
    assess_verdict: str = ""
    assess_conf: float = 0.0
    assess_summary: str = ""
    reported: bool = False
    cost_usd: float = 0.0
    seconds: float = 0.0

    @property
    def test_hash(self) -> str:
        return hashlib.sha256(self.test_code.encode("utf-8")).hexdigest()[:16]


class Ledger:
    def __init__(self, path: Path | str = ".jittest/ledger.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def record(self, c: Candidate) -> int:
        cur = self.conn.execute(
            "INSERT INTO candidates (created, schema_version, repo, pr, base_rev,"
            " head_rev, file_path, symbol, risk_score, risk_reasons, model, attempt,"
            " test_hash, test_code, oracle_catching, oracle_reason, latent,"
            " assess_verdict, assess_conf, assess_summary, reported, cost_usd, seconds)"
            " VALUES (?,2,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                time.time(), c.repo, c.pr, c.base_rev, c.head_rev, c.file_path,
                c.symbol, c.risk_score, json.dumps(c.risk_reasons), c.model,
                c.attempt, c.test_hash, c.test_code, int(c.oracle_catching),
                c.oracle_reason, int(c.latent), c.assess_verdict, c.assess_conf,
                c.assess_summary, int(c.reported), c.cost_usd, c.seconds,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def mark_outcome(self, candidate_id: int, outcome: str, note: str = "") -> None:
        if outcome not in HUMAN_OUTCOMES:
            raise ValueError(f"outcome must be one of {HUMAN_OUTCOMES}")
        self.conn.execute(
            "UPDATE candidates SET human_outcome=?, human_note=?, human_at=? WHERE id=?",
            (outcome, note, time.time(), candidate_id),
        )
        self.conn.commit()

    def mark_outcome_by_hash(self, test_hash: str, outcome: str, note: str = "") -> int:
        if outcome not in HUMAN_OUTCOMES:
            raise ValueError(f"outcome must be one of {HUMAN_OUTCOMES}")
        cur = self.conn.execute(
            "UPDATE candidates SET human_outcome=?, human_note=?, human_at=?"
            " WHERE test_hash=?",
            (outcome, note, time.time(), test_hash),
        )
        self.conn.commit()
        return cur.rowcount

    def stats(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, SUM(oracle_catching) AS catching,"
            " SUM(reported) AS reported, SUM(latent) AS latent, SUM(cost_usd) AS cost,"
            " COUNT(DISTINCT repo) AS repos, COUNT(DISTINCT pr) AS prs FROM candidates"
        ).fetchone()
        total = row["total"] or 0
        catching = row["catching"] or 0
        reported = row["reported"] or 0

        outcomes = {
            r["human_outcome"]: r["n"]
            for r in self.conn.execute(
                "SELECT human_outcome, COUNT(*) AS n FROM candidates"
                " WHERE human_outcome IS NOT NULL GROUP BY human_outcome"
            )
        }
        labelled = sum(outcomes.values())
        good = outcomes.get("fixed_code", 0) + outcomes.get("kept_test", 0)

        return {
            "candidates": total,
            "catching": catching,
            "reported": reported,
            "latent": row["latent"] or 0,
            "repos": row["repos"] or 0,
            "pull_requests": row["prs"] or 0,
            "total_cost_usd": round(row["cost"] or 0.0, 4),
            "catch_rate": round(catching / total, 4) if total else None,
            "report_rate": round(reported / total, 4) if total else None,
            "human_outcomes": outcomes,
            "labelled": labelled,
            "true_positive_rate": round(good / labelled, 4) if labelled else None,
            "false_positive_rate": (
                round(outcomes.get("false_positive", 0) / labelled, 4)
                if labelled else None
            ),
        }

    def export_jsonl(self, out_path: Path | str, anonymise: bool = True) -> int:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with out.open("w", encoding="utf-8") as fh:
            for row in self.conn.execute("SELECT * FROM candidates ORDER BY id"):
                rec = dict(row)
                if anonymise:
                    salt = "jittest-corpus-v1"
                    for key in ("repo", "file_path", "pr"):
                        value = rec.get(key) or ""
                        rec[key] = (
                            hashlib.sha256((salt + value).encode()).hexdigest()[:12]
                            if value else ""
                        )
                    for key in ("test_code", "human_note", "base_rev", "head_rev"):
                        rec.pop(key, None)
                    rec["symbol"] = "redacted" if rec.get("symbol") else ""
                fh.write(json.dumps(rec) + "\n")
                written += 1
        return written
