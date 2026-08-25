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
first version of this gate. A second adversarial sweep on 2026-08-25 ran 35
payloads through the exact bytes then on `main` and 24 were accepted, so the
previous claim that all 16 were rejected was wrong: classes 1, 3, 5 and 6
were closed only for the specific spellings first tested. What is closed,
mitigated and still accepted is listed in `docs/HARDENING.md` with the
executed verdict for every payload. This gate is a filter, not a proof.
Receipt integrity also depends on the worktree reset in
`jittest.execute.reset_workdir`, which runs once per candidate per side.
The classes were:

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
    # Network egress. Executed 2026-08-25: payloads N9, N9b and N10
    # reached sockets or a third-party HTTP client with none of the
    # names above appearing anywhere in the candidate.
    "ssl", "imaplib", "poplib", "nntplib", "xmlrpc", "socketserver",
    "smtpd", "asyncore", "asynchat", "paramiko", "pycurl",
    "websockets", "websocket", "aiohttp", "httpcore", "curl_cffi",
    "openai", "litellm", "anthropic", "cohere", "replicate", "groq",
    "mistralai", "huggingface_hub", "fsspec", "botocore", "s3transfer",
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
    # Process creation. `spawnl/spawnv/spawnve` were listed; the p and
    # e suffixed variants and posix_spawn were not. Receipt N11.
    "posix_spawn", "posix_spawnp", "spawnlp", "spawnle", "spawnlpe",
    "spawnvp", "spawnvpe", "forkpty",
    # asyncio reaches subprocess and sockets without importing either.
    # Receipts N8 and N9.
    "create_subprocess_exec", "create_subprocess_shell",
    "open_connection", "open_unix_connection", "start_server",
    "start_unix_server",
}

# `from <anything> import <name>` where the name itself is the dangerous part.
BANNED_IMPORT_NAMES = BANNED_ATTRS | BANNED_CALLS | {"remove", "replace", "rename"}

# Modules whose attributes reach a process or the filesystem. Used only to
# decide whether a *receiver* is dangerous, never to ban a method name.
_MUTATOR_RECEIVER_MODULES = {
    "os", "io", "shutil", "pathlib", "tarfile", "zipfile", "tempfile",
    "subprocess", "posix", "nt",
}

# A candidate is a claim about behaviour. One that reads the source under
# test and asserts on its text fails on head and passes on base for a
# reason that is not the change - a manufactured catch built from no
# banned construct at all. Receipts N14 and N15.
_SOURCE_SUFFIXES = (".py", ".pyi", ".pyx", ".pxd")
_PROVENANCE_PATHS = (".git", ".hg", ".svn")

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


_TEMP_TOKENS = (
    "tmp_path", "tmpdir", "tmp_path_factory", "tmpdir_factory", "tempfile",
    "mkdtemp", "mkstemp", "temporarydirectory", "namedtemporaryfile",
    "gettempdir", "tmpfile",
)
_PATH_CTORS = ("Path", "PurePath", "PosixPath", "WindowsPath", "PurePosixPath")
_HARD_MUTATORS = {
    "remove", "replace", "rename", "renames", "truncate", "link", "utime",
    "putenv", "unsetenv", "extract", "extractall",
}


def _looks_like_mode(text: str) -> bool:
    """True for plausible open() mode strings like "w", "rb", "a+"."""
    return (0 < len(text) <= 4
            and set(text) <= set("rwxab+tU")
            and bool(set(text) & set("rwxa")))


def _any_open_mode(node: ast.Call) -> str | None:
    """The mode of an open() call whether it arrived as Name or Attribute.

    `open(p, "w")` puts the mode second; `Path(p).open("w")` puts it first.
    The original _open_mode only ever looked at args[1], so every attribute
    form was invisible to the write-mode check.
    """
    for arg in node.args:
        if _is_const_str(arg) and _looks_like_mode(arg.value):
            return arg.value
    for kw in node.keywords:
        if kw.arg == "mode" and _is_const_str(kw.value):
            return kw.value.value
    return None


def _path_expressions(node: ast.Call) -> list[ast.AST]:
    """Every sub-expression that could name the file an open() call touches."""
    modes = {id(a) for a in node.args
             if _is_const_str(a) and _looks_like_mode(a.value)}
    out: list[ast.AST] = [a for a in node.args if id(a) not in modes]
    out += [kw.value for kw in node.keywords
            if kw.arg in ("file", "path", "name", "filename")]
    if isinstance(node.func, ast.Attribute):
        out.append(node.func.value)
    return out


def _target_literals(node: ast.Call) -> list[str]:
    """String literals anywhere inside the path expression of an open() call."""
    found: list[str] = []
    for expr in _path_expressions(node):
        for sub in ast.walk(expr):
            if _is_const_str(sub):
                found.append(sub.value)
    return found


def _is_tree_path(text: str) -> bool:
    """True when a literal names source or repository metadata under test."""
    norm = text.replace(chr(92), "/").strip()
    if not norm:
        return False
    if norm.split("/", 1)[0] in _PROVENANCE_PATHS or "/.git" in norm:
        return True
    return norm.endswith(_SOURCE_SUFFIXES)


def _rooted_in_temp(node: ast.Call) -> bool:
    dumped = " ".join(ast.dump(e) for e in _path_expressions(node)).lower()
    return any(token in dumped for token in _TEMP_TOKENS)


def _is_mutator_receiver(func: ast.Attribute, aliases: set[str]) -> bool:
    """True when the receiver is os/io/pathlib-ish rather than a str or list.

    This is what makes it safe to reject `os.remove` while still accepting
    `str.replace` and `list.remove`: the decision is made on the receiver, not
    on the method name, so the false-positive rate is zero by construction.
    """
    recv = func.value
    if isinstance(recv, ast.Name):
        return recv.id in aliases
    if isinstance(recv, ast.Attribute):
        base = recv.value
        return isinstance(base, ast.Name) and base.id in aliases
    if isinstance(recv, ast.Call) and isinstance(recv.func, ast.Name):
        return recv.func.id in _PATH_CTORS
    return False

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
    # The same distinction for attributes, which was absent. That absence
    # was the whole of the 2026-08-24 external finding: `invoke = os.system`
    # never puts an Attribute in Call.func position, so the BANNED_ATTRS
    # check below could not see it. Receipts P1 and P2.
    called_attr_nodes = {
        id(node.func) for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    # Local names bound to a dangerous module or to a Path(...), so
    # receiver-bound mutators can be rejected without banning method names
    # that collide with str.replace and list.remove.
    aliases: set[str] = set()
    for pre in ast.walk(tree):
        if isinstance(pre, ast.Import):
            for alias in pre.names:
                if _root(alias.name) in _MUTATOR_RECEIVER_MODULES:
                    aliases.add(alias.asname or _root(alias.name))
        elif isinstance(pre, ast.ImportFrom):
            if pre.module and _root(pre.module) in _MUTATOR_RECEIVER_MODULES:
                for alias in pre.names:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(pre, ast.Assign):
            value = pre.value
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in _PATH_CTORS):
                for target in pre.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)

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
            if isinstance(node.test, (ast.List, ast.Tuple, ast.Dict, ast.Set)) \
                    and (getattr(node.test, "elts", None)
                         or getattr(node.test, "keys", None)):
                # Class 6 was closed for `assert 1` and `assert 'yes'` but not
                # for `assert [1]`, `assert (1,)` or `assert {"a": 1}`, which
                # are non-empty literals and so unconditionally truthy.
                # Receipts N7a, N7b, N7c.
                return CodeCheck(
                    False,
                    "asserts a non-empty literal container, which proves nothing")

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

        if (isinstance(node, ast.Attribute)
                and id(node) not in called_attr_nodes
                and node.attr in BANNED_ATTRS):
            return CodeCheck(
                False,
                f"references banned attribute `{node.attr}` without calling it")

        if (isinstance(node, ast.Subscript)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"):
            # Assignment is a Subscript store, not a Call, so no call-based
            # rule could ever see it. Receipt N12c.
            return CodeCheck(False, "assigns into `os.environ`")

        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                return CodeCheck(False, f"calls banned builtin `{func.id}`")
            if (isinstance(func, ast.Name)
                    and func.id in ("getattr", "setattr", "delattr")
                    and (len(node.args) < 2 or not _is_const_str(node.args[1]))):
                    return CodeCheck(
                        False, f"computed attribute access via `{func.id}`")
            if (isinstance(func, ast.Name)
                    and func.id in ("getattr", "setattr", "delattr")
                    and len(node.args) > 1
                    and _is_const_str(node.args[1])
                    and node.args[1].value in (
                        BANNED_ATTRS | BANNED_CALLS | BANNED_DUNDERS)):
                # Only *computed* second arguments were rejected. A literal
                # one produced no Attribute node named `system` anywhere in
                # the tree, so class 3 was open. Receipt P3.
                return CodeCheck(
                    False,
                    f"reaches banned name `{node.args[1].value}` via `{func.id}`")
            if ((isinstance(func, ast.Name) and func.id == "open")
                    or (isinstance(func, ast.Attribute) and func.attr == "open")):
                # `Path(p).open("w")`, `io.open(p, "w")` and
                # `codecs.open(p, "w")` were all accepted because this
                # check only looked at ast.Name and only read args[1].
                # Receipts P4, P4b, P4c.
                mode = _any_open_mode(node)
                literals = _target_literals(node)
                tree_literal = next(
                    (t for t in literals if _is_tree_path(t)), None)
                if tree_literal is not None:
                    verb = "writes" if (mode and set(mode) & _WRITE_MODES) else "reads"
                    return CodeCheck(
                        False,
                        f"{verb} `{tree_literal}`, which is inside the tree "
                        "under test; a candidate that touches the source or "
                        "the git metadata instead of the behaviour differs "
                        "between base and head for a reason that is not the "
                        "change")
                if mode and (set(mode) & _WRITE_MODES):
                    # A hard-coded write target is the tamper vector: a
                    # candidate that rewrites a source file in the worktree
                    # can manufacture a base/head difference. A computed
                    # path is how legitimate fixtures use scratch files
                    # (temp dirs, paths derived from __file__), so that is
                    # warned about rather than rejected.
                    hard = next(
                        (t for t in literals if not _looks_like_mode(t)),
                        None)
                    if hard is not None and not _rooted_in_temp(node):
                        return CodeCheck(
                            False,
                            f"opens the hard-coded path "
                            f"`{hard}` with mode `{mode}`; a "
                            "candidate that writes into the worktree can "
                            "corrupt the base/head comparison")
                    if not _rooted_in_temp(node):
                        warnings.append(
                            f"opens a computed path with mode `{mode}`")
            if isinstance(func, ast.Attribute):
                if func.attr in BANNED_ATTRS:
                    return CodeCheck(False, f"calls `{func.attr}`")
                if (func.attr in _HARD_MUTATORS
                        and _is_mutator_receiver(func, aliases)):
                    # `remove`, `replace` and `rename` are excluded from
                    # BANNED_ATTRS on purpose, because `str.replace` and
                    # `list.remove` appear in ordinary tests constantly. The
                    # fix is to decide on the receiver instead of the name,
                    # which costs zero false positives by construction.
                    # Receipts P5, P5b, P5c, N12a.
                    return CodeCheck(
                        False,
                        f"calls `{func.attr}` on a filesystem or process "
                        "receiver, which can corrupt the base/head comparison")
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
