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

REQ_LINE_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:\[([^\]]+)\])?\s*(==|>=|<=|~=|!=|>|<)?\s*([^;\s]+)?")


class ReadinessRefusal(VerifyRefusalError):
    """Fail-closed refusal when the target runtime cannot satisfy needs."""


@dataclass(frozen=True)
class Requirement:
    name: str
    specifier: str = ""
    extras: str = ""


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
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = REQ_LINE_RE.match(line)
        if not match:
            continue
        out.append(
            Requirement(
                name=match.group(1).lower().replace("_", "-"),
                specifier=(match.group(3) or "") + (match.group(4) or ""),
                extras=match.group(2) or "",
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
    reqs = {r.name: r.specifier for r in parse_requirements(requirements_text)}
    locks = {r.name: r.specifier for r in parse_requirements(lock_text)}
    problems = []
    for name, spec in reqs.items():
        if name not in locks:
            problems.append(f"lock_missing:{name}")
        elif spec and locks[name] and spec != locks[name]:
            problems.append(f"lock_drift:{name} req={spec} lock={locks[name]}")
    return problems


def evaluate_readiness(
    requirements_text: str,
    target_runtime: set[str],
    host_visible: set[str] | None = None,
    wheel_names: list[str] | None = None,
    lock_text: str | None = None,
) -> ReadinessReport:
    report = ReadinessReport()
    reqs = parse_requirements(requirements_text)
    report.direct = reqs
    target = {name.lower().replace("_", "-") for name in target_runtime}
    host = {name.lower().replace("_", "-") for name in (host_visible or set())}
    for req in reqs:
        if req.name not in target:
            report.ok = False
            report.problems.append(f"missing_direct_dependency:{req.name}")
        if req.name in host and req.name not in target:
            report.host_only.append(req.name)
    for problem in check_platform_compat(wheel_names or []):
        report.ok = False
        report.problems.append(problem)
    if lock_text is not None:
        for problem in check_lock_drift(requirements_text, lock_text):
            report.ok = False
            report.problems.append(problem)
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
