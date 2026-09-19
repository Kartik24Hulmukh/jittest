# PR 224 continuation: frozen before source changes

Starting SHA: c7fc5d7178f85182cfdcf714450840dc8ba1c79d. PR open, not merged; Windows 3.11 and aggregate CI failing. Historical metrics are not fresh measurements.

Five failure modes: (1) JIT/process-tree exit races; (2) reader/thread starvation under concurrent descendants; (3) seed/state drift; (4) unbounded stdout/stderr capture in proc._drain; (5) descendants survive parent exit because kill_process_tree returns early.

Gates: zero unhandled exceptions, zero surviving owned readers/children, bounded captured output; cleanup and clean readiness recovery strictly <200ms, report total wall-clock separately. 100 workers, >=100 personas, 1000 requests, seed 20260919, PYTHONHASHSEED=0. Report P50/P95/P99, throughput, RSS floor/ceiling without calling two RSS samples proof of zero leaks. 100 workers is concurrency, not evidence of 100x baseline throughput. Full unit/integration/E2E and all remote checks must pass before merging. No changed thresholds, sleeps, fake dependencies or skipped failing tests. Maximum five fix cycles/module, then escalation.

Known independent CI failure: 60-second pytest guard expires inside a 90-second pip install of PyYAML. Dependency provisioning test currently depends on live package index/network.
