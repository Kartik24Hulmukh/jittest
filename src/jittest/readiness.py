"""Deterministic readiness checks (handoff P0-3).

Detects missing direct/transitive dependencies, lock/specifier drift,
ABI/platform incompatibility and packages visible on the host but
absent from the declared target runtime. Pure-python and deterministic:
the same inputs always yield the same verdict, and any gap refuses.
"""

from __future__ import annotations

import importlib.util
import platform
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .verify import VerifyRefusalError

_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"

# PEP 508 subset: name, extras, direct URL, comma-separated specifier set, marker.
REQ_LINE_RE = re.compile(
    r"^(?P<name>" + _NAME + r")\s*"
    r"(?:\[(?P<extras>[^\]]*)\])?\s*"
    r"(?:@\s*(?P<url>[^;\s]+))?\s*"
    r"(?P<spec>(?:(?:===|==|!=|>=|<=|~=|>|<)\s*[^,;\s]+\s*,?\s*)*)"
    r"(?:;\s*(?P<marker>.+?))?\s*$"
)
_SPEC_RE = re.compile(r"(===|==|!=|>=|<=|~=|>|<)\s*([^,;\s]+)")
_MARKER_CLAUSE_RE = re.compile(
    r"^\s*(?P<left>[A-Za-z_][A-Za-z_.0-9]*|'[^']*'|\"[^\"]*\")\s*"
    r"(?P<op>===|==|!=|>=|<=|~=|>|<|not in|in)\s*"
    r"(?P<right>[A-Za-z_][A-Za-z_.0-9]*|'[^']*'|\"[^\"]*\")\s*$"
)
SUPPORTED_MARKER_VARS = frozenset(
    {
        "python_version",
        "python_full_version",
        "sys_platform",
        "platform_system",
        "platform_machine",
        "os_name",
        "implementation_name",
        "extra",
    }
)


class UnsupportedMarker(Exception):
    """Raised when a marker expression is outside the supported PEP 508 subset."""


def normalize_name(name: str) -> str:
    """PEP 503 normalisation: runs of -_. collapse to a single dash, lowercased."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def parse_version(text: str) -> tuple:
    """Deterministic, total ordering key for a release version string."""
    core = str(text).strip().lstrip("vV").split("+", 1)[0]
    core = re.split(r"[-_]?(?:a|b|rc|alpha|beta|dev|post)", core, maxsplit=1)[0]
    parts = []
    for chunk in core.split("."):
        if chunk == "*" or chunk == "":
            break
        digits = re.match(r"\d+", chunk)
        parts.append(int(digits.group(0)) if digits else 0)
    return tuple(parts) or (0,)


def _pad(a: tuple, b: tuple) -> tuple:
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)), b + (0,) * (width - len(b))


def specifier_satisfied(specifier: str, version: str) -> bool:
    """True when *version* satisfies every clause of a PEP 440 specifier set."""
    if not specifier:
        return True
    if not version:
        return False
    have = parse_version(version)
    for op, want_raw in _SPEC_RE.findall(specifier):
        want = parse_version(want_raw)
        if op in ("==", "===") and want_raw.endswith(".*"):
            prefix = parse_version(want_raw[:-2])
            if have[: len(prefix)] != prefix:
                return False
            continue
        left, right = _pad(have, want)
        if op in ("==", "===") and left != right:
            return False
        if op == "!=" and left == right:
            return False
        if op == ">=" and left < right:
            return False
        if op == "<=" and left > right:
            return False
        if op == ">" and left <= right:
            return False
        if op == "<" and left >= right:
            return False
        if op == "~=":
            floor = want
            ceiling = want[:-1][:-1] + (want[-2] + 1,) if len(want) >= 2 else None
            lf, rf = _pad(have, floor)
            if lf < rf:
                return False
            if ceiling is not None:
                lc, rc = _pad(have, ceiling)
                if lc >= rc:
                    return False
    return True


def marker_environment(target_python: str | None = None, extra: str = "") -> dict:
    """Deterministic marker environment for the declared target runtime."""
    full = target_python or current_python()
    short = ".".join(full.split(".")[:2])
    return {
        "python_version": short,
        "python_full_version": full,
        "sys_platform": sys.platform,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "os_name": "posix" if sys.platform != "win32" else "nt",
        "implementation_name": sys.implementation.name,
        "extra": extra,
    }


def _marker_operand(token: str, env: dict):
    if token[:1] in ("'", '"'):
        return token[1:-1], False
    if token in SUPPORTED_MARKER_VARS:
        return env.get(token, ""), True
    raise UnsupportedMarker(token)


def _eval_marker_clause(clause: str, env: dict) -> bool:
    match = _MARKER_CLAUSE_RE.match(clause)
    if not match:
        raise UnsupportedMarker(clause.strip())
    left, is_var_l = _marker_operand(match.group("left"), env)
    right, is_var_r = _marker_operand(match.group("right"), env)
    op = match.group("op")
    if op == "in":
        return str(left) in str(right)
    if op == "not in":
        return str(left) not in str(right)
    version_like = (is_var_l and match.group("left").startswith("python")) or (
        is_var_r and match.group("right").startswith("python")
    )
    if op in ("==", "===", "!=") and not version_like:
        return (str(left) == str(right)) if op != "!=" else (str(left) != str(right))
    if version_like or op in (">", ">=", "<", "<=", "~="):
        return specifier_satisfied(op + str(right), str(left))
    raise UnsupportedMarker(clause.strip())


def evaluate_marker(marker: str, env: dict | None = None) -> bool:
    """Evaluate a supported marker subset. Unsupported input fails closed."""
    if not marker or not marker.strip():
        return True
    environment = env if env is not None else marker_environment()
    text = marker.strip()
    if "(" in text or ")" in text:
        raise UnsupportedMarker(text)
    result = None
    pending = "or"
    for or_part in re.split(r"\bor\b", text):
        and_value = True
        for and_part in re.split(r"\band\b", or_part):
            and_value = and_value and _eval_marker_clause(and_part, environment)
        result = and_value if result is None else (result or and_value)
        pending = "or"
    return bool(result)


class ReadinessRefusal(VerifyRefusalError):
    """Fail-closed refusal when the target runtime cannot satisfy needs."""


@dataclass(frozen=True)
class Requirement:
    name: str
    specifier: str = ""
    extras: str = ""
    marker: str = ""
    url: str = ""

    def applies(self, env: dict | None = None) -> bool:
        """Whether this requirement is active for the given marker environment."""
        return evaluate_marker(self.marker, env)


@dataclass
class ReadinessReport:
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    direct: list = field(default_factory=list)
    transitive: list = field(default_factory=list)
    host_only: list = field(default_factory=list)

    def raise_if_bad(self) -> None:
        if not self.ok:
            raise ReadinessRefusal("readiness_failed: " + "; ".join(self.problems))


def parse_requirements(text: str) -> list:
    """Parse a PEP 508 subset. Names are PEP 503 normalised; order preserved."""
    out = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(chr(92)):
            buffer += line[:-1].strip() + " "
            continue
        line, buffer = buffer + line, ""
        if line.startswith("-"):
            continue
        match = REQ_LINE_RE.match(line)
        if not match:
            continue
        specs = [op + val for op, val in _SPEC_RE.findall(match.group("spec") or "")]
        extras = (match.group("extras") or "").split(",")
        out.append(
            Requirement(
                name=normalize_name(match.group("name")),
                specifier=",".join(specs),
                extras=",".join(sorted(e.strip().lower() for e in extras if e.strip())),
                marker=(match.group("marker") or "").strip(),
                url=(match.group("url") or "").strip(),
            )
        )
    return out


def module_visible(name: str) -> bool:
    return importlib.util.find_spec(name.replace("-", "_")) is not None


def check_platform_compat(wheel_names: list[str]) -> list[str]:
    problems = []
    system = platform.system().lower()
    machine = platform.machine().lower()
    for wheel in wheel_names:
        lowered = wheel.lower()
        if "-any.whl" in lowered:
            continue
        tags = lowered.replace(".whl", "").split("-")
        plat = tags[-1] if len(tags) >= 3 else ""
        if plat and system not in plat and "any" not in plat:
            problems.append(f"platform_incompatible:{wheel}")
        if plat and machine.replace("x86_64", "amd64") not in plat and "any" not in plat and machine not in plat:
            problems.append(f"abi_incompatible:{wheel}")
    return problems


def check_lock_drift(requirements_text: str, lock_text: str) -> list[str]:
    """Semantic drift: a lock pin must actually satisfy the declared range."""
    reqs = parse_requirements(requirements_text)
    locks = {r.name: r for r in parse_requirements(lock_text)}
    problems = []
    for req in reqs:
        locked = locks.get(req.name)
        if locked is None:
            problems.append(f"lock_missing:{req.name}")
            continue
        pins = [v for op, v in _SPEC_RE.findall(locked.specifier) if op in ("==", "===")]
        if pins:
            if not specifier_satisfied(req.specifier, pins[0]):
                problems.append(f"lock_drift:{req.name} req={req.specifier} lock=={pins[0]}")
        elif req.specifier and locked.specifier and req.specifier != locked.specifier:
            problems.append(f"lock_drift:{req.name} req={req.specifier} lock={locked.specifier}")
        elif not locked.specifier:
            problems.append(f"lock_unpinned:{req.name}")
    return problems


def evaluate_readiness(
    requirements_text: str,
    target_runtime,
    host_visible: set[str] | None = None,
    wheel_names: list[str] | None = None,
    lock_text: str | None = None,
    target_python: str | None = None,
    extras: str = "",
) -> ReadinessReport:
    """Fail-closed readiness verdict.

    ``target_runtime`` may be a set of distribution names or a mapping of
    name -> installed version; a mapping additionally enables version-aware
    specifier checking. Unsupported markers and direct URL requirements
    refuse rather than silently passing.
    """
    report = ReadinessReport()
    env = marker_environment(target_python, extras)
    if isinstance(target_runtime, dict):
        versions = {normalize_name(k): str(v) for k, v in target_runtime.items()}
    else:
        versions = {normalize_name(name): "" for name in target_runtime}
    target = set(versions)
    host = {normalize_name(name) for name in (host_visible or set())}
    active = []
    for req in parse_requirements(requirements_text):
        if req.url:
            report.ok = False
            report.problems.append(f"direct_url_unsupported:{req.name}")
            continue
        try:
            if not req.applies(env):
                continue
        except UnsupportedMarker as exc:
            report.ok = False
            report.problems.append(f"unsupported_marker:{req.name}:{exc}")
            continue
        active.append(req)
        if req.name not in target:
            report.ok = False
            report.problems.append(f"missing_direct_dependency:{req.name}")
        elif versions[req.name] and not specifier_satisfied(req.specifier, versions[req.name]):
            report.ok = False
            report.problems.append(
                f"version_conflict:{req.name} have={versions[req.name]} want={req.specifier}"
            )
        if req.name in host and req.name not in target:
            report.host_only.append(req.name)
    report.direct = active
    for problem in check_platform_compat(wheel_names or []):
        report.ok = False
        report.problems.append(problem)
    if lock_text is not None:
        for problem in check_lock_drift(requirements_text, lock_text):
            report.ok = False
            report.problems.append(problem)
    report.problems.sort()
    return report


def scan_imports(source_dir: Path | str) -> list[str]:
    """Best-effort transitive dependency surface from import statements."""
    found: set[str] = set()
    import_re = re.compile(r"^\s*(?:import|from)\s+([A-Za-z0-9_]+)")
    for path in Path(source_dir).rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            match = import_re.match(line)
            if match:
                found.add(match.group(1))
    return sorted(found)


def host_stdlib_shadow(names: list[str]) -> list[str]:
    """Names visible on this host interpreter but not stdlib-builtin."""
    missing = []
    for name in names:
        if importlib.util.find_spec(name) is None:
            missing.append(name)
    return missing


def current_python() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
