"""Configuration with a boring, predictable precedence chain:

    dataclass defaults  ->  .jittest.toml  ->  [tool.jittest] in pyproject.toml
    ->  JITTEST_* environment variables  ->  command line flags

Read with stdlib `tomllib`. No PyYAML, no pydantic.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path

__all__ = ["Config", "load_config", "DEFAULT_IGNORES"]

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

    valid = {f for f in Config.__dataclass_fields__}
    extra_ignores = values.pop("ignore", None)
    cfg = Config(**{k: v for k, v in values.items() if k in valid})

    if extra_ignores:
        cfg.ignore = list(DEFAULT_IGNORES) + list(extra_ignores)

    ignore_file = repo / ".jittestignore"
    if ignore_file.exists():
        try:
            lines = ignore_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        cfg.ignore += [ln.strip() for ln in lines
                       if ln.strip() and not ln.strip().startswith("#")]

    return cfg
