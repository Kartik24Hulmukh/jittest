"""Static gate on generated test code, applied before anything is executed.

We are about to run model-written Python inside someone else's CI runner. The
oracle needs execution, so the answer is not "do not execute" - it is "execute
only code that has no business talking to the outside world".

This is a static AST check, not a security boundary. It stops accidents and
obvious prompt-injection payloads. It does not stop a determined attacker who
controls the model, which is why SECURITY.md tells you to run jittest on
`pull_request` (no secrets) rather than `pull_request_target`.

Hardening history: an adversarial sweep of 28 payloads (see
`tests/test_hardening.py`) found 16 accepted-but-dangerous constructs in the
first version of this gate. All 16 are now rejected. The classes were:

1. `from os import system` - the module was allowed and the callable arrived as
   a bare Name, so neither the module check nor the attribute check fired.
2. Builtin aliasing - `f = eval` then `f(...)`, which defeats a check that only
   looks at `Call.func`.
3. Reflection - `getattr(os, 'sys' + 'tem')`, `importlib.import_module`,
   `builtins.eval`, `runpy.run_module`.
4. Interpreter gadgets - `''.__class__.__mro__[1].__subclasses__()` and
   `func.__globals__`.
5. Filesystem mutation - a candidate that rewrites a source file inside the
   worktree can corrupt the base/head comparison the oracle depends on, so a
   "catching" test could be manufactured rather than discovered.
6. Vacuous assertions - `assert 1` and `assert 'yes'` prove exactly as little
   as `assert True`, which was already rejected.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

__all__ = [
    "CodeCheck", "check_candidate", "BANNED_MODULES", "BANNED_CALLS",
    "BANNED_ATTRS", "BANNED_IMPORT_NAMES", "BANNED_DUNDERS",
]

BANNED_MODULES = {
    "socket", "http", "urllib", "urllib3", "requests", "httpx", "ftplib",
    "smtplib", "telnetlib", "subprocess", "multiprocessing", "ctypes",
    "shutil", "pty", "pickle", "marshal", "webbrowser", "boto3",
    # Reflection and dynamic execution: every one of these is a one-liner
    # around something already on the list above.
    "importlib", "builtins", "runpy", "code", "codeop", "imp",
}

# Bare-name callables. A candidate test has no legitimate reason to reach any
# of these, and `globals`/`locals`/`vars` are the standard escape hatch for
# reaching the ones that are blocked.
BANNED_CALLS = {
    "eval", "exec", "compile", "__import__", "breakpoint", "input",
    "globals", "locals", "vars",
}

# Attribute calls. Deliberately excludes common, harmless method names that
# collide with dangerous ones - `str.replace`, `list.remove` and `file.write`
# appear in ordinary tests constantly, so banning them by name would reject
# more good candidates than bad ones.
BANNED_ATTRS = {
    "system", "popen", "execv", "execve", "execl", "execlp", "execvp",
    "execvpe", "spawnl", "spawnv", "spawnve", "startfile", "fork", "kill",
    "killpg", "abort", "_exit", "setuid", "setgid", "chroot",
    # Reflection.
    "import_module", "load_module", "run_module", "run_path",
    # Filesystem mutation, which can corrupt the base/head comparison.
    "rmtree", "unlink", "rmdir", "mkfifo", "symlink", "chmod", "chown",
    "write_text", "write_bytes",
}

# `from <anything> import <name>` where the name itself is the dangerous part.
BANNED_IMPORT_NAMES = BANNED_ATTRS | BANNED_CALLS | {"remove", "replace", "rename"}

# Interpreter internals used to walk from a harmless object to a dangerous one.
# `__class__` is deliberately allowed: tests check types legitimately.
BANNED_DUNDERS = {
    "__subclasses__", "__mro__", "__globals__", "__code__", "__builtins__",
    "__bases__", "__closure__", "__getattribute__", "__reduce__",
    "__reduce_ex__",
}

_WRITE_MODES = set("wax+")
SUSPICIOUS_TEXT = ("api_key", "secret", "os.environ[", "getenv(", "/etc/passwd", ".ssh")


@dataclass
class CodeCheck:
    ok: bool
    reason: str = ""
    warnings: tuple[str, ...] = ()


def _root(name: str) -> str:
    return name.split(".")[0]


def _is_const_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _open_mode(node: ast.Call) -> str | None:
    """The literal mode string passed to `open`, if there is one."""
    if len(node.args) >= 2 and _is_const_str(node.args[1]):
        return node.args[1].value  # type: ignore[union-attr,return-value]
    for kw in node.keywords:
        if kw.arg == "mode" and _is_const_str(kw.value):
            return kw.value.value  # type: ignore[union-attr,return-value]
    return None


APPROVED_UNITTEST_ASSERTIONS = {
    "assertEqual", "assertNotEqual", "assertTrue", "assertFalse",
    "assertIs", "assertIsNot", "assertIsNone", "assertIsNotNone",
    "assertIn", "assertNotIn", "assertInstanceOf", "assertNotInstanceOf",
    "assertRaises", "assertRegex", "assertAlmostEqual", "assertCountEqual",
}


def check_candidate(code: str, max_bytes: int = 20000) -> CodeCheck:
    if not code.strip():
        return CodeCheck(False, "empty candidate")
    if len(code.encode("utf-8")) > max_bytes:
        return CodeCheck(False, "candidate is implausibly large")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CodeCheck(False, f"syntax error: {exc.msg} at line {exc.lineno}")
    except ValueError as exc:                      # embedded null bytes
        return CodeCheck(False, f"invalid source: {exc}")

    has_test = False
    has_assert = False
    warnings: list[str] = []

    # Names that appear as the callee of a call, so the alias check below can
    # tell `eval(x)` (reported as a banned call) from `f = eval` (reported as a
    # banned reference). Both are rejected; only the message differs.
    called_name_nodes = {
        id(node.func) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name.startswith("test_"):
            has_test = True

        if isinstance(node, ast.Assert):
            has_assert = True
            if isinstance(node.test, ast.Constant):
                if node.test.value is True:
                    return CodeCheck(False, "contains `assert True`, which proves nothing")
                return CodeCheck(
                    False, f"asserts the constant `{node.test.value!r}`, which proves nothing")

        if isinstance(node, ast.With):
            for item in node.items:
                ctx_expr = ast.unparse(item.context_expr)
                if "pytest.raises" in ctx_expr or "raises(" in ctx_expr:
                    has_assert = True

        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) in BANNED_MODULES:
                    return CodeCheck(False, f"imports banned module `{alias.name}`")

        if isinstance(node, ast.ImportFrom):
            if node.module and _root(node.module) in BANNED_MODULES:
                return CodeCheck(False, f"imports banned module `{node.module}`")
            for alias in node.names:
                if alias.name in BANNED_IMPORT_NAMES:
                    return CodeCheck(
                        False,
                        f"imports banned name `{alias.name}` from `{node.module or '.'}`")

        if isinstance(node, ast.Name) and id(node) not in called_name_nodes \
                and node.id in BANNED_CALLS:
            return CodeCheck(False, f"references banned builtin `{node.id}` without calling it")

        if isinstance(node, ast.Attribute) and node.attr in BANNED_DUNDERS:
            return CodeCheck(False, f"reaches interpreter internals via `{node.attr}`")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                return CodeCheck(False, f"calls banned builtin `{func.id}`")
            if (isinstance(func, ast.Name)
                    and func.id in ("getattr", "setattr", "delattr")
                    and (len(node.args) < 2 or not _is_const_str(node.args[1]))):
                    return CodeCheck(
                        False, f"computed attribute access via `{func.id}`")
            if isinstance(func, ast.Name) and func.id == "open":
                mode = _open_mode(node)
                if mode and (set(mode) & _WRITE_MODES):
                    # A hard-coded write target is the tamper vector: a
                    # candidate that rewrites a source file in the worktree
                    # can manufacture a base/head difference. A computed
                    # path is how legitimate fixtures use scratch files
                    # (temp dirs, paths derived from __file__), so that is
                    # warned about rather than rejected.
                    if node.args and _is_const_str(node.args[0]):
                        return CodeCheck(
                            False,
                            f"opens the hard-coded path "
                            f"`{node.args[0].value}` with mode `{mode}`; a "  # type: ignore[union-attr]
                            "candidate that writes into the worktree can "
                            "corrupt the base/head comparison")
                    warnings.append(f"opens a computed path with mode `{mode}`")
            if isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id in ("self", "test"):
                    if func.attr in APPROVED_UNITTEST_ASSERTIONS or func.attr.startswith("assert"):
                        has_assert = True
                if func.attr in BANNED_ATTRS:
                    return CodeCheck(False, f"calls `{func.attr}`")
                if func.attr == "sleep":
                    return CodeCheck(False, "calls sleep, which is a flakiness source")

    if not has_test:
        return CodeCheck(False, "no function named test_*")
    if not has_assert:
        return CodeCheck(False, "no assertion")

    lowered = code.lower()
    for token in SUSPICIOUS_TEXT:
        if token in lowered:
            warnings.append(f"mentions `{token}`")

    return CodeCheck(True, "", tuple(warnings))
