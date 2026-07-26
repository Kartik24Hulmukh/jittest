"""Static gate on generated test code, applied before anything is executed.

We are about to run model-written Python inside someone else's CI runner. The
oracle needs execution, so the answer is not "do not execute" - it is "execute
only code that has no business talking to the outside world".

This is a static AST check, not a security boundary. It stops accidents and
obvious prompt-injection payloads. It does not stop a determined attacker who
controls the model, which is why SECURITY.md tells you to run jittest on
`pull_request` (no secrets) rather than `pull_request_target`.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass

__all__ = ["CodeCheck", "check_candidate", "BANNED_MODULES", "BANNED_CALLS"]

BANNED_MODULES = {
    "socket", "http", "urllib", "urllib3", "requests", "httpx", "ftplib",
    "smtplib", "telnetlib", "subprocess", "multiprocessing", "ctypes",
    "shutil", "pty", "pickle", "marshal", "webbrowser", "boto3",
}
BANNED_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}
BANNED_ATTRS = {"system", "popen", "execv", "execve", "fork", "kill", "rmtree"}
SUSPICIOUS_TEXT = ("api_key", "secret", "os.environ[", "getenv(", "/etc/passwd", ".ssh")


@dataclass
class CodeCheck:
    ok: bool
    reason: str = ""
    warnings: tuple[str, ...] = ()


def _root(name: str) -> str:
    return name.split(".")[0]


def check_candidate(code: str, max_bytes: int = 20000) -> CodeCheck:
    if not code.strip():
        return CodeCheck(False, "empty candidate")
    if len(code.encode("utf-8")) >= max_bytes:
        return CodeCheck(False, "candidate is implausibly large")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return CodeCheck(False, f"syntax error: {exc.msg} at line {exc.lineno}")

    has_test = False
    has_assert = False
    warnings: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                node.name.startswith("test_"):
            has_test = True
        if isinstance(node, ast.Assert):
            has_assert = True
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                return CodeCheck(False, "contains `assert True`, which proves nothing")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) in BANNED_MODULES:
                    return CodeCheck(False, f"imports banned module `{alias.name}`")
        if isinstance(node, ast.ImportFrom) and node.module and _root(node.module) in BANNED_MODULES:
            return CodeCheck(False, f"imports banned module `{node.module}`")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                return CodeCheck(False, f"calls banned builtin `{func.id}`")
            if isinstance(func, ast.Attribute):
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
