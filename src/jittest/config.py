"""Configuration with a boring, predictable precedence chain:

    dataclass defaults  ->  .jittest.toml  ->  [tool.jittest] in pyproject.toml
    ->  JITTEST_* environment variables  ->  command line flags

Read with stdlib `tomllib`. No PyYAML, no pydantic.

Every value is type-checked and range-clamped before it reaches the rest of the
program. This is not defensiveness for its own sake: a stress sweep found that
`JITTEST_BUDGET_USD=nan` produced a config whose `as_dict()` could not be
serialised as strict JSON, which silently corrupts the telemetry artifact the
evaluation harness reads, and `risk_threshold=5.0` produced a run that analysed
nothing while reporting success. Both are the kind of failure that looks like
"the tool found nothing" rather than "the tool was misconfigured".
"""
from __future__ import annotations

import math
import os
import tomllib
from dataclasses import MISSING, asdict, dataclass, field, fields
from fnmatch import fnmatch
from pathlib import Path

__all__ = ["Config", "load_config", "DEFAULT_IGNORES", "normalise_values"]

# Generated, vendored or throwaway code. Testing it wastes money and reviewer
# patience in equal measure.
DEFAULT_IGNORES = [
    "*/migrations/*", "*/vendor/*", "*/vendored/*", "*/node_modules/*",
    "*/.venv/*", "*/venv/*", "*/build/*", "*/dist/*", "*/__pycache__/*",
    "*_pb2.py", "*_pb2_grpc.py", "*.pyi", "setup.py", "conftest.py",
    "*/docs/*", "*/examples/*",
]

_ENV = {
    "model": ("JITTEST_MODEL", str),
    "budget_usd": ("JITTEST_BUDGET_USD", float),
    "max_targets": ("JITTEST_MAX_TARGETS", int),
    "candidates_per_target": ("JITTEST_CANDIDATES", int),
    "risk_threshold": ("JITTEST_RISK_THRESHOLD", float),
    "timeout_s": ("JITTEST_TIMEOUT", int),
    "reruns": ("JITTEST_RERUNS", int),
    "min_confidence": ("JITTEST_MIN_CONFIDENCE", float),
    "ledger_path": ("JITTEST_LEDGER", str),
    "sandbox_mode": ("JITTEST_SANDBOX", str),
    "sandbox_backend": ("JITTEST_SANDBOX_BACKEND", str),
    "sandbox_image": ("JITTEST_SANDBOX_IMAGE", str),
}

# Free-text options that are nevertheless not free: an unrecognised value here
# would silently disable isolation, which is the one setting where a typo must
# not be interpreted charitably.
_ENUMS: dict[str, tuple[str, ...]] = {
    "sandbox_mode": ("auto", "required", "off"),
    "sandbox_backend": ("", "podman", "docker", "bubblewrap"),
}

# field -> (kind, low, high). Bounds are inclusive.
_LIMITS: dict[str, tuple[type, float, float]] = {
    "budget_usd": (float, 0.0, 1000.0),
    "max_targets": (int, 1, 200),
    "candidates_per_target": (int, 1, 20),
    "risk_threshold": (float, 0.0, 1.0),
    "timeout_s": (int, 1, 3600),
    "reruns": (int, 0, 10),
    "temperature": (float, 0.0, 2.0),
    "min_confidence": (float, 0.0, 1.0),
    "repair_attempts": (int, 0, 5),
}


@dataclass
class Config:
    model: str = "anthropic/claude-sonnet-4-5"
    budget_usd: float = 1.00
    max_targets: int = 5
    candidates_per_target: int = 4
    risk_threshold: float = 0.35
    timeout_s: int = 120
    reruns: int = 2
    temperature: float = 0.8
    min_confidence: float = 0.70
    repair_attempts: int = 1
    latent_mode: bool = False
    fail_on_regression: bool = False
    ledger_path: str = ".jittest/ledger.db"
    cache_path: str = ".jittest/cache.db"
    # Isolation. "auto" uses a container or namespace backend when one is
    # present and records a warning when one is not. "required" refuses to run
    # unconfined - the correct setting for pull requests from strangers, whose
    # text reaches the generator prompt and therefore chooses the code that is
    # about to be executed. "off" is the pre-0.2.5 behaviour.
    sandbox_mode: str = "auto"
    sandbox_backend: str = ""
    sandbox_image: str = "python:3.13-slim"
    ignore: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORES))

    def is_ignored(self, path: str) -> bool:
        p = path.replace("\\", "/")
        name = p.split("/")[-1]
        for pattern in self.ignore:
            if fnmatch(p, pattern) or fnmatch(name, pattern) or fnmatch("/" + p, pattern):
                return True
        return False

    def as_dict(self) -> dict:
        return asdict(self)


def _defaults() -> dict:
    out: dict = {}
    for f in fields(Config):
        if f.default_factory is not MISSING:      # type: ignore[misc]
            out[f.name] = f.default_factory()    # type: ignore[misc]
        else:
            out[f.name] = f.default
    return out


def normalise_values(values: dict) -> tuple[dict, list[str]]:
    """Drop unknown keys, coerce types, clamp ranges. Never raises.

    Returns the cleaned mapping and a list of human-readable notes describing
    every correction, so `doctor` can tell the user their config was wrong
    instead of quietly doing something else.
    """
    defaults = _defaults()
    clean: dict = {}
    notes: list[str] = []

    for key, raw in values.items():
        if key not in defaults:
            notes.append(f"ignored unknown option `{key}`")
            continue
        default = defaults[key]

        if key in _ENUMS:
            text = str(raw).strip().lower() if raw is not None else ""
            if text not in _ENUMS[key]:
                notes.append(
                    f"`{key}` was {raw!r}, which is not one of "
                    f"{', '.join(v or '(empty)' for v in _ENUMS[key])}; "
                    f"using the default {default!r}")
                clean[key] = default
            else:
                clean[key] = text
            continue

        if key == "ignore":
            if isinstance(raw, str):
                notes.append("`ignore` must be a list of patterns; ignored a bare string")
                continue
            if not isinstance(raw, (list, tuple)):
                notes.append(f"`ignore` must be a list, got {type(raw).__name__}; ignored")
                continue
            clean[key] = [str(x) for x in raw]
            continue

        if isinstance(default, bool):
            clean[key] = bool(raw)
            continue

        if key in _LIMITS:
            kind, low, high = _LIMITS[key]
            # bool is an int subclass, and `budget_usd = true` is never intended.
            if isinstance(raw, bool):
                notes.append(f"`{key}` was a boolean; using default {default}")
                clean[key] = default
                continue
            try:
                value = kind(raw)
            except (TypeError, ValueError):
                notes.append(f"`{key}` must be a number, got {raw!r}; using default {default}")
                clean[key] = default
                continue
            if isinstance(value, float) and not math.isfinite(value):
                notes.append(f"`{key}` was {raw!r} (not a finite number); using default {default}")
                clean[key] = default
                continue
            if value < low:
                notes.append(f"`{key}` {value} is below the minimum {low}; clamped")
                value = kind(low)
            elif value > high:
                notes.append(f"`{key}` {value} is above the maximum {high}; clamped")
                value = kind(high)
            clean[key] = value
            continue

        if isinstance(default, str):
            if not isinstance(raw, str):
                notes.append(f"`{key}` must be a string, got {type(raw).__name__}; "
                             f"using default {default!r}")
                clean[key] = default
                continue
            clean[key] = raw
            continue

        clean[key] = raw

    return clean, notes


def _from_toml(repo: Path) -> dict:
    for filename, section in ((".jittest.toml", None), ("pyproject.toml", "jittest")):
        path = repo / filename
        if not path.exists():
            continue
        try:
            with path.open("rb") as fh:
                data = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if section:
            data = data.get("tool", {}).get(section, {})
        elif "jittest" in data and isinstance(data["jittest"], dict):
            data = data["jittest"]
        if data:
            return dict(data)
    return {}


def _from_env() -> dict:
    out: dict = {}
    for key, (env_name, caster) in _ENV.items():
        raw = os.getenv(env_name)
        if raw is None or raw == "":
            continue
        try:
            out[key] = caster(raw)
        except ValueError:
            continue
    return out


def load_config(repo: Path | str = ".", overrides: dict | None = None) -> Config:
    repo = Path(repo)
    values: dict = {}
    values.update(_from_toml(repo))
    values.update(_from_env())
    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = value

    values, notes = normalise_values(values)

    extra_ignores = values.pop("ignore", None)
    cfg = Config(**values)

    if extra_ignores:
        cfg.ignore = list(DEFAULT_IGNORES) + list(extra_ignores)

    ignore_file = repo / ".jittestignore"
    if ignore_file.exists():
        try:
            lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        cfg.ignore += [ln.strip() for ln in lines
                       if ln.strip() and not ln.strip().startswith("#")]

    # Not a dataclass field on purpose: `as_dict()` stays a clean, strictly
    # JSON-serialisable snapshot of configuration only.
    cfg.notes = tuple(notes)  # type: ignore[attr-defined]
    return cfg
