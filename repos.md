# repos.md - open-source catalog used to harden and stress jittest

Every tool below is upstream open source. The **Integration** column says exactly how
jittest uses it; **Runtime dep?** is always *no* because `pyproject.toml` keeps
`dependencies = []` on purpose (jittest runs inside other people's CI).

| # | Repository | License | Used for | Integration | Runtime dep? |
|---|------------|---------|----------|-------------|--------------|
| 1 | https://github.com/python/cpython (`subprocess`, `http.server`, `tracemalloc`, `threading.excepthook`) | PSF | native waits, probe server, leak + panic detection | `proc.run_bounded` now blocks on `Popen.wait(timeout=)`; swarm captures thread panics via `threading.excepthook` and peaks via `tracemalloc` | stdlib |
| 2 | https://github.com/pytest-dev/pytest | MIT | unit / integration / E2E runner | `[project.optional-dependencies].dev`; 1211-test suite | dev only |
| 3 | https://github.com/pytest-dev/pytest-xdist | MIT | 100x-parallel test execution (`-n 8`) to shake out ordering/race bugs | used for the frozen baseline + post-change full run | dev only |
| 4 | https://github.com/pytest-dev/pytest-timeout | MIT | thread-starvation guard: no test may hang the suite | `--timeout` on every CI run; subprocess timeouts on process-boundary regressions | dev only |
| 5 | https://github.com/HypothesisWorks/hypothesis | MPL-2.0 | fixed-seed property testing of erratic payload shapes | `tests/test_persona_swarm_100x.py::test_probe_app_never_raises_and_always_answers_json` (`derandomize=True`, 200 examples); skipped cleanly if absent | dev only |
| 6 | https://github.com/astral-sh/ruff | MIT | lint + import hygiene gate | `ruff check` clean on every touched file | dev only |
| 7 | https://github.com/python/mypy | MIT | static typing gate | `[dev]` extra | dev only |
| 8 | https://github.com/open-telemetry/opentelemetry-python | Apache-2.0 | distributed tracing contract | `prod/wsgi.ProbeApp(tracer=...)` accepts any OTel-compatible tracer; `prod/tracing.py` is a zero-dep tracer with the same `span()`/`set_attribute()` surface | optional, host-provided |
| 9 | https://github.com/locustio/locust | MIT | pattern source for user-journey load generation | persona model (one function per human behaviour, shuffled out-of-order, fixed seed) reimplemented stdlib-only in `scripts/persona_swarm_100x.py` | no |
| 10 | https://github.com/tsenart/vegeta | MIT | pattern source for constant-rate bursts + p50/p95/p99 reports | burst phase + nearest-rank percentiles in the swarm JSON artefact | no |
| 11 | https://github.com/Netflix/chaosmonkey | Apache-2.0 | chaos design: RST dropouts, slowloris, garbage bytes | `network_dropout_rst`, `slow_half_request`, `garbage_bytes` personas | no |
| 12 | https://github.com/kubernetes/kubernetes (probe semantics) | Apache-2.0 | `/healthz` vs `/readyz` contract, HEAD support, drain-before-stop | `prod/probes.py`, `prod/wsgi.py` | no |
| 13 | https://github.com/prometheus/client_python | Apache-2.0 | metrics export contract | JSON metrics artefact is shaped so a host can lift it into Prometheus gauges; no client library is imported | no |
| 14 | https://github.com/pyca/cryptography / RFC 8032 | Apache-2.0 | Ed25519 receipt signing reference | `_ed25519.py` is a stdlib implementation verified against the reference test vectors | no |
| 15 | https://github.com/containers/podman, https://github.com/moby/moby | Apache-2.0 | trusted-image inventory probe with `--network none` (Option C, PR #221) | `env.py` / `sandbox` backends | external binary |
| 16 | https://github.com/containers/bubblewrap | LGPL-2.0 | non-container sandbox backend | `env.py` (skips image probe) | external binary |

## Integration log for `harden/jittest-v1-launch` (2026-09-19)

1. **cpython `Popen.wait`** replaced the 20 ms `poll()`/`time.sleep(0.02)` loop in
   `proc.run_bounded`. `time` is no longer imported by `proc.py`; `src/` keeps a single
   deliberate sleep (`llm._sleep`, request pacing, injectable for tests).
2. **pytest-xdist + pytest-timeout** ran the frozen baseline: 1211 passed, 1 skipped,
   202 subtests, 177 s on 8 workers, before any source change.
3. **hypothesis** added as a optional dev dependency (conditional class definition) for the erratic-payload
   property test; the rest of the swarm is stdlib-only so CI without hypothesis stays green.
4. **locust / vegeta / chaosmonkey** patterns informed the 20 persona kinds and the
   burst/percentile/recovery report shape; no code was vendored.

## Continuation: optional-dependency CI repair

Hypothesis is now declared in the dev extra and installed in the pytest CI lane.
The dependency-free lane still runs first, without installing any package.
A separate subprocess regression uses `python -S` to prove discovery succeeds
even when the developer environment has Hypothesis installed. This repairs
the import-time decorator failure without adding a runtime dependency.

## PR 224 continuation integrations

CPython subprocess and existing pytest tooling only; no new runtime stack.
CI stages the real PyYAML 6.0.3 native wheel using existing pip before the
60-second fixture deadline, and native provisioning runs with both pip/uv
indexes disabled. This is not a mock or an increased recovery threshold.

## Continuation: provisioning identity + budget (PR #224, 2026-09-19)

Root cause of the `test (windows-latest, 3.11)` red on PR #224: the venv cache key
included the commit sha, so base and head with byte-identical `requirements.txt`
built two venvs (2x venv creation, 2x3 network installs) inside one 60 s
pytest-timeout budget; per-step installer caps (90+90+60+60 s) summed past the
caller's deadline so exhaustion surfaced as an untyped kill.

| # | Repository | Taken | Where |
|---|------------|-------|-------|
| 1 | https://github.com/python/cpython (`hashlib`, `time.perf_counter`) | content-addressed env identity; monotonic provisioning deadline | `env.env_cache_identity`, `env._ProvisionDeadline` |
| 17 | https://github.com/pypa/pip | `--no-input --prefer-binary --disable-pip-version-check` on the fallback installer: no credential-prompt wedge, no native build when a wheel exists, no self-check round-trip | `env.provision_environment.run_installer` |
| 18 | https://github.com/astral-sh/uv | `--exclude-newer` is the only resolver that applies the era cutoff, so the cutoff enters the identity only when uv is present | `env.env_cache_identity` |

Frozen swarm (seed 20260919, 100 workers, 1000-request burst, `PYTHONHASHSEED=0`,
run concurrently with the full suite): p50 91.3 ms / p95 107.6 ms / p99 119.7 ms,
1040.8 rps, RSS 29.3 -> 52.7 MiB, tracemalloc peak 11.0 MiB, recovery 1.04 ms,
0 unhandled panics, 0 unexpected statuses, no registry drift.

## 2026-09-26 continuation integrations

Existing CPython `contextlib.ExitStack` and `tempfile.TemporaryFile` now own
capture resources across spawn failures and cancellation; `math.isfinite`
rejects invalid budgets; `DEVNULL` removes the unused pipe-reader fallback.
Linux regression uses CPython `os.pidfd_open` + `select` for a real kernel
exit notification within 199 ms, not a sleep or mock. Existing ruff, mypy,
pytest, xdist and hypothesis provide verification. No new runtime dependency.
`psutil` was installed in the sandbox but was not integrated or used as evidence.

This is a partial repair, not launch approval: capture disk usage is still
unbounded, Windows job containment is absent, and the independent 100-process
recovery gate failed. The probe-plane swarm is not evidence of 100x engine
throughput. Recovery timestamps now include capture decoding and resource
closure, previously excluded by `t_join_end`.
