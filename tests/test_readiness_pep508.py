"""PEP 508/503 regression suite for the readiness gate (launch hardening)."""

import unittest

from jittest.readiness import (
    ReadinessRefusal,
    UnsupportedMarker,
    check_lock_drift,
    evaluate_marker,
    evaluate_readiness,
    marker_environment,
    normalize_name,
    parse_requirements,
    parse_version,
    specifier_satisfied,
)


class TestNormalization(unittest.TestCase):
    def test_pep503_normalization_collapses_separator_runs(self):
        for raw in ("Flask_Foo", "flask.foo", "FLASK--FOO", "Flask_._Foo"):
            self.assertEqual(normalize_name(raw), "flask-foo")

    def test_parse_normalizes_and_preserves_order(self):
        reqs = parse_requirements("B_pkg>=1\nA.Pkg==2\n")
        self.assertEqual([r.name for r in reqs], ["b-pkg", "a-pkg"])


class TestSpecifiers(unittest.TestCase):
    def test_version_ordering_is_total_and_deterministic(self):
        self.assertLess(parse_version("1.9.0"), parse_version("1.10"))
        self.assertEqual(parse_version("v2.0.1+local"), parse_version("2.0.1"))
        self.assertEqual(parse_version("1.2.3rc1"), parse_version("1.2.3"))

    def test_range_and_exclusion_clauses(self):
        self.assertTrue(specifier_satisfied(">=1.0,<2.0", "1.5"))
        self.assertFalse(specifier_satisfied(">=1.0,<2.0", "2.0"))
        self.assertFalse(specifier_satisfied("!=1.5", "1.5"))

    def test_compatible_release_and_wildcard(self):
        self.assertTrue(specifier_satisfied("~=1.4", "1.9"))
        self.assertFalse(specifier_satisfied("~=1.4", "2.0"))
        self.assertTrue(specifier_satisfied("==1.2.*", "1.2.9"))
        self.assertFalse(specifier_satisfied("==1.2.*", "1.3.0"))

    def test_empty_specifier_accepts_and_missing_version_refuses(self):
        self.assertTrue(specifier_satisfied("", "anything"))
        self.assertFalse(specifier_satisfied(">=1", ""))


class TestMarkers(unittest.TestCase):
    def test_python_version_comparison_uses_version_semantics(self):
        env = marker_environment("3.10.4")
        self.assertTrue(evaluate_marker('python_version >= "3.9"', env))
        self.assertFalse(evaluate_marker('python_version < "3.0"', env))

    def test_and_or_and_membership(self):
        env = marker_environment("3.11.0")
        env["sys_platform"] = "linux"
        self.assertTrue(evaluate_marker('python_version >= "3.8" and sys_platform != "win32"', env))
        self.assertTrue(evaluate_marker('sys_platform == "win32" or python_version >= "3.8"', env))
        self.assertTrue(evaluate_marker('"lin" in sys_platform', env))

    def test_unsupported_marker_fails_closed(self):
        with self.assertRaises(UnsupportedMarker):
            evaluate_marker('platform_release == "6.1"')
        with self.assertRaises(UnsupportedMarker):
            evaluate_marker('(python_version > "3")')

    def test_empty_marker_is_always_active(self):
        self.assertTrue(evaluate_marker(""))


class TestEvaluateReadiness(unittest.TestCase):
    def test_inactive_marker_requirement_is_not_required(self):
        report = evaluate_readiness('six; python_version < "3.0"', {"requests": "2.31.0"}, target_python="3.11.0")
        self.assertTrue(report.ok, report.problems)
        self.assertEqual(report.direct, [])

    def test_version_aware_conflict_is_reported(self):
        report = evaluate_readiness("requests>=2.0", {"requests": "1.9"})
        self.assertFalse(report.ok)
        self.assertIn("version_conflict:requests have=1.9 want=>=2.0", report.problems)
        with self.assertRaises(ReadinessRefusal):
            report.raise_if_bad()

    def test_direct_url_requirement_refuses(self):
        report = evaluate_readiness("pkg @ https://example.invalid/pkg.whl", {"pkg": "1.0"})
        self.assertFalse(report.ok)
        self.assertIn("direct_url_unsupported:pkg", report.problems)

    def test_unsupported_marker_requirement_refuses(self):
        report = evaluate_readiness('pkg; platform_release == "6.1"', {"pkg": "1.0"})
        self.assertFalse(report.ok)
        self.assertTrue(any(p.startswith("unsupported_marker:pkg") for p in report.problems))

    def test_name_form_mismatch_still_resolves(self):
        report = evaluate_readiness("Flask_Foo>=1.0", {"flask-foo": "1.2"})
        self.assertTrue(report.ok, report.problems)

    def test_legacy_set_target_runtime_still_supported(self):
        self.assertTrue(evaluate_readiness("requests>=2.0", {"requests"}).ok)
        self.assertFalse(evaluate_readiness("requests>=2.0", set()).ok)

    def test_problems_are_sorted_for_determinism(self):
        text = "zeta>=1\nalpha>=1\n"
        first = evaluate_readiness(text, set()).problems
        self.assertEqual(first, sorted(first))
        self.assertEqual(first, evaluate_readiness(text, set()).problems)


class TestLockDrift(unittest.TestCase):
    def test_pin_satisfying_range_is_not_drift(self):
        self.assertEqual(check_lock_drift("requests>=2.0", "requests==2.31.0"), [])

    def test_pin_violating_range_is_drift(self):
        self.assertEqual(
            check_lock_drift("requests>=3.0", "requests==2.31.0"),
            ["lock_drift:requests req=>=3.0 lock==2.31.0"],
        )

    def test_missing_and_unpinned_lock_entries(self):
        self.assertEqual(check_lock_drift("requests>=2.0", ""), ["lock_missing:requests"])
        self.assertEqual(check_lock_drift("requests>=2.0", "requests"), ["lock_unpinned:requests"])


if __name__ == "__main__":
    unittest.main()
