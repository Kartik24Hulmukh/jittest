# Worker operational probes (unreleased)

`jittest` is a CLI execution gate, not a multi-tenant SaaS. `ProbeApp` is an
optional WSGI adapter for a deployment supervisor; it is not automatically
started by the CLI, and does not attest sandbox or dependency readiness.

```python
import logging
from jittest.prod import ProbeApp

logger = logging.getLogger("jittest.probes")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
application = ProbeApp(logger=logger)  # starts NOT ready
# Only after your worker, queue, sandbox and required dependencies initialize:
application.set_ready(True)
# On shutdown, BEFORE stopping admission and waiting for in-flight jobs:
# application.drain()
```

Mount `application` in a bounded production WSGI server on a private management
listener. Do not expose Python's development wsgiref server publicly. Configure
worker/thread limits, connection/read timeouts, queue bounds and ingress rate
limits. This adapter intentionally has no execution or arbitrary-path endpoint.
Each worker has its own state; use process-aware routing, not a detached sidecar
that stays ready when workers die. Readiness transitions are lock-protected;
drain is terminal and an out-of-order ready update cannot undo it. Restart
begins not-ready. The host must supply startup checks and crash reconciliation.

| Route | Meaning | Status |
|---|---|---|
| `/healthz` | Process can answer HTTP; stays alive during drain | 200 |
| `/readyz` | Supervisor marked initialized and not draining | 200 or 503 |
| Unknown route | No arbitrary-path handling | 404 |
| Non-GET/HEAD on probes | No mutation through HTTP | 405 |

Responses are canonical JSON with `Cache-Control: no-store`; HEAD has matching
content length and no body. Readiness is cached: no network, disk or user code
is executed to evaluate the verdict. Configure short health-check deadlines.

## OpenTelemetry and JSON logs

Core package dependencies remain empty. Optional tracing integrates a real
OpenTelemetry-compatible tracer supplied by the embedding service:

```python
# Install opentelemetry-sdk separately in your supervisor environment.
from opentelemetry.sdk.trace import TracerProvider
from jittest.prod import ProbeApp
provider = TracerProvider()
# Add your bounded batch exporter here, configured with explicit timeouts.
application = ProbeApp(tracer=provider.get_tracer("jittest.probes"))
```

Spans are named `jittest.probe`, with bounded `http.route` and numeric
`http.response.status_code`. JSON log records contain event, route, status and
monotonic duration_ms only. Arbitrary paths, headers, payloads, secret values and
exception text are not logged. Exporter/logger exceptions do not alter the
verdict; synchronous hooks can still block, so the host MUST use a bounded,
nonblocking logging/export pipeline with drop counters and shutdown flushing.
Tracing covers the probe, NOT the core verify pipeline; this is not a claim of
end-to-end tracing. No global handlers, threads or SDK providers are installed.

## Reproduce

```sh
python -m pytest tests/test_prod.py tests/test_stress_100x.py tests/test_chaos_resilience.py
python scripts/bench_integrity.py --output benchmark.json
```

The benchmark uses seed 20260913, 100 versus 10,000 integrity build/compare
jobs and 1 versus 32 threads. It exports service P50/P95/P99, throughput, traced
peak/retained bytes, Linux process peak RSS, environment, source revision and
ordered result digest. Queue wait is excluded from service latency; tracemalloc
adds overhead. RSS is a process-lifetime maximum and includes input/result
storage. Single-run microbenchmarks do not prove end-to-end capacity or absence
of all memory leaks. Run on quiet dedicated hardware repeatedly for SLO gates.
Real Docker kill/reconciliation remains NOT_RUN in this environment.
