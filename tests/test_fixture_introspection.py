"""Owned dependency-free lazy-object regressions for fixture discovery."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from jittest import _pytestshim as shim
from jittest._fixtureengine import _fixture_marker_of, _fixtures_from, _FixtureState


class FixtureIntrospection(unittest.TestCase):
    def test_unbound_lazy_nonfixture_does_not_run_getattr(self):
        calls = []

        class UnboundProxy:
            def __getattr__(self, name):
                calls.append(name)
                raise RuntimeError("owned proxy outside context")

        module = ModuleType("owned_lazy_conftest")
        module.proxy = UnboundProxy()
        self.assertEqual(_fixtures_from(module), {})
        self.assertEqual(calls, [])

    def test_marker_properties_are_not_executed_or_registered(self):
        for attr in (shim.FIXTURE_MARKER, "_pytestfixturefunction", "_fixture_function_marker"):
            with self.subTest(attr=attr):
                calls = []

                def unbound_getter(self, calls=calls, attr=attr):
                    calls.append(attr)
                    raise RuntimeError("owned descriptor outside context")

                lazy_type = type("OwnedDescriptorProxy", (), {attr: property(unbound_getter)})
                proxy = lazy_type()
                self.assertIsNone(_fixture_marker_of(proxy))
                module = ModuleType("owned_descriptor_conftest")
                module.proxy = proxy
                self.assertEqual(_fixtures_from(module), {})
                self.assertEqual(calls, [])

    def test_real_pytest_decorator_is_unwrapped_and_executed(self):
        try:
            import pytest
        except ModuleNotFoundError as exc:
            if exc.name != "pytest":
                raise
            self.skipTest("real pytest decorator requires optional installed pytest")
        calls = []

        @pytest.fixture(name="real_answer", scope="module")
        def answer():
            calls.append("executed")
            return 42

        module = ModuleType("owned_real_pytest_fixture")
        module.answer = answer
        registry = _fixtures_from(module)
        self.assertEqual(set(registry), {"real_answer"})
        state = _FixtureState()
        self.assertEqual(state.resolve("real_answer", registry, {}), 42)
        self.assertEqual(calls, ["executed"])
        state.finish_module()

    def test_custom_marker_descriptors_and_forwarded_class_are_not_evaluated(self):
        calls = []

        class Descriptor:
            def __get__(self, instance, owner):
                calls.append("descriptor")
                raise RuntimeError("owned descriptor evaluated")

        class LazyProxy:
            __jittest_fixture__ = Descriptor()
            _pytestfixturefunction = Descriptor()
            _fixture_function_marker = Descriptor()

            def __getattr__(self, attr):
                calls.append(attr)
                raise RuntimeError("owned dynamic lookup evaluated")

        def forwarded_class(self):
            calls.append("class")
            raise RuntimeError("owned forwarded class evaluated")

        proxy_type = type("OwnedForwardedClass", (LazyProxy,), {"__class__": property(forwarded_class)})
        module = ModuleType("owned_custom_descriptor_conftest")
        module.proxy = proxy_type()
        self.assertEqual(_fixtures_from(module), {})
        self.assertEqual(calls, [])

    def test_shim_fixture_metadata_and_execution_are_preserved(self):
        calls = []

        @shim.fixture(name="answer", scope="module", params=[41], ids=["owned"], autouse=True)
        def original(request):
            calls.append(request.param)
            return request.param + 1

        module = ModuleType("owned_shim_conftest")
        module.original = original
        registry = _fixtures_from(module)
        self.assertEqual(set(registry), {"answer"})
        definition = registry["answer"]
        self.assertIs(definition.fn, original)
        self.assertEqual(definition.scope, "module")
        self.assertEqual(definition.params, [41])
        self.assertEqual(definition.ids, ["owned"])
        self.assertTrue(definition.autouse)
        state = _FixtureState()
        self.assertEqual(state.resolve("answer", registry, {"answer": (0, 41)}), 42)
        self.assertEqual(calls, [41])
        state.finish_module()

    def test_stored_alternative_marker_attributes_are_retained(self):
        for attr in ("_pytestfixturefunction", "_fixture_function_marker"):
            with self.subTest(attr=attr):
                def answer():
                    return 42

                marker = shim.FixtureDef(answer, name="answer")
                setattr(answer, attr, marker)
                module = ModuleType("owned_stored_marker")
                module.answer = answer
                registry = _fixtures_from(module)
                self.assertIs(_fixture_marker_of(answer), marker)
                state = _FixtureState()
                self.assertEqual(state.resolve("answer", registry, {}), 42)
                state.finish_function()

    def test_property_marker_does_not_hide_stored_alternative_fixture(self):
        calls = []
        marker = shim.FixtureDef(lambda: 42, name="answer")

        class ActualFixture:
            _fixture_function_marker = marker

            @property
            def __jittest_fixture__(self):
                calls.append("property")
                raise RuntimeError("owned property evaluated")

            def __call__(self):
                calls.append("fixture")
                return 42

        module = ModuleType("owned_property_with_real_marker")
        module.answer = ActualFixture()
        registry = _fixtures_from(module)
        state = _FixtureState()
        self.assertEqual(state.resolve("answer", registry, {}), 42)
        self.assertEqual(calls, ["fixture"])
        state.finish_function()

    def test_nonfixture_proxy_does_not_mask_fixture_execution_error(self):
        calls = []

        class UnboundProxy:
            def __getattr__(self, name):
                calls.append(name)
                raise RuntimeError("owned irrelevant proxy")

        @shim.fixture
        def broken():
            raise ValueError("owned genuine fixture failure")

        module = ModuleType("owned_failing_fixture")
        module.proxy = UnboundProxy()
        module.broken = broken
        registry = _fixtures_from(module)
        self.assertEqual(set(registry), {"broken"})
        with self.assertRaisesRegex(ValueError, "owned genuine fixture failure"):
            _FixtureState().resolve("broken", registry, {})
        self.assertEqual(calls, [])

    def test_malformed_stored_marker_error_still_propagates(self):
        class BrokenMarker:
            @property
            def scope(self):
                raise ValueError("owned malformed fixture marker")

        def answer():
            return 42

        answer.__jittest_fixture__ = BrokenMarker()
        module = ModuleType("owned_malformed_fixture")
        module.answer = answer
        with self.assertRaisesRegex(ValueError, "owned malformed fixture marker"):
            _fixtures_from(module)

    def test_owned_conftest_lazy_proxy_does_not_block_minirunner_execution(self):
        self._owned_minirunner_fixture(fail=False)

    def test_owned_conftest_lazy_proxy_does_not_mask_minirunner_fixture_failure(self):
        self._owned_minirunner_fixture(fail=True)

    def _owned_minirunner_fixture(self, *, fail):
        with tempfile.TemporaryDirectory(prefix="fixture-introspection-") as temporary:
            root = Path(temporary)
            result = ("raise ValueError('owned genuine fixture failure')" if fail else "return 42")
            (root / "conftest.py").write_text(
                "import pytest\nfrom pathlib import Path\n"
                "class UnboundProxy:\n"
                "    def __getattr__(self, attr):\n"
                "        raise RuntimeError('owned lazy proxy outside context')\n"
                "proxy = UnboundProxy()\n"
                "@pytest.fixture\n"
                "def answer():\n"
                "    Path('fixture_executed.txt').write_text('executed')\n"
                f"    {result}\n", encoding="utf-8")
            candidate = root / "test_owned.py"
            candidate.write_text(
                "from pathlib import Path\ndef test_owned(answer):\n"
                "    assert answer == 42\n"
                "    Path('test_executed.txt').write_text('executed')\n", encoding="utf-8")
            env = {k: os.environ[k] for k in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC") if k in os.environ}
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            completed = subprocess.run([sys.executable, "-S", "-m", "jittest._minirunner", str(candidate)],
                                       cwd=root, env=env, capture_output=True, timeout=20)
            self.assertEqual(completed.returncode, 1 if fail else 0, completed.stderr)
            self.assertEqual((root / "fixture_executed.txt").read_text(), "executed")
            self.assertEqual((root / "test_executed.txt").exists(), not fail)
            self.assertNotIn(b"owned lazy proxy outside context", completed.stderr)
            if fail:
                self.assertIn(b"owned genuine fixture failure", completed.stderr)


if __name__ == "__main__":
    unittest.main()
