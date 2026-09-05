"""Parametrised negative receipt corpus tests covering Task 17 (J2)."""

from pathlib import Path

import pytest

from jittest.cli import main
from jittest.receipt import verify_receipt

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "receipts" / "negative"


CASES = [
    (
        "missing_provenance.json",
        {},
        "schema_status",
        "INVALID",
    ),
    (
        "pass_pass_proven_catch.json",
        {},
        "semantic_valid",
        False,
    ),
    (
        "empty_actual_sha.json",
        {"expected_base": "a" * 40},
        "schema_status",
        "INVALID",
    ),
    (
        "substring_repo.json",
        {"expected_repo": "github.com/foo/bar"},
        "provenance_status",
        "MISMATCH",
    ),
    (
        "non_object_input.json",
        {},
        "signature_valid",
        False,
    ),
    (
        "unknown_signer.json",
        {"expected_signer": "deadbeef" * 8, "strict_signer": True},
        "signer_status",
        "UNTRUSTED",
    ),
    (
        "short_signer_prefix.json",
        {"expected_signer": "12345678", "strict_signer": True},
        "signer_status",
        "INVALID_FORMAT",
    ),
    (
        "tampered_byte.json",
        {},
        "signature_valid",
        False,
    ),
    (
        "unknown_future_schema.json",
        {},
        "schema_status",
        "UNSUPPORTED",
    ),
    (
        "legacy_hmac.json",
        {},
        "signature_valid",
        False,
    ),
]


@pytest.mark.parametrize("filename,kwargs,field,expected_val", CASES)
def test_negative_corpus_field_rejection(
    filename: str, kwargs: dict, field: str, expected_val: object
):
    fixture_path = FIXTURES_DIR / filename
    assert fixture_path.is_file(), f"missing fixture {fixture_path}"

    res = verify_receipt(fixture_path, **kwargs)
    assert not res.valid, f"expected receipt {filename} to be rejected"
    actual_val = getattr(res, field)
    assert actual_val == expected_val, (
        f"for {filename}, expected res.{field} == {expected_val!r}, got {actual_val!r} (reason: {res.reason})"
    )


CLI_CASES = [
    ("tampered_byte.json", [], 2),
    ("unknown_signer.json", ["--strict-signer", "--expected-signer", "deadbeef" * 8], 3),
    ("missing_provenance.json", [], 4),
    ("unknown_future_schema.json", [], 4),
    ("pass_pass_proven_catch.json", [], 5),
    ("substring_repo.json", ["--expected-repo", "github.com/foo/bar"], 6),
]


@pytest.mark.parametrize("filename,extra_args,expected_exit_code", CLI_CASES)
def test_negative_corpus_cli_exit_codes(
    filename: str, extra_args: list[str], expected_exit_code: int
):
    fixture_path = FIXTURES_DIR / filename
    argv = ["verify-receipt", str(fixture_path), *extra_args]
    rc = main(argv)
    assert rc == expected_exit_code, (
        f"for CLI {argv}, expected exit code {expected_exit_code}, got {rc}"
    )
