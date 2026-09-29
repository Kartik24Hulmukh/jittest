from eval.ga73_smoke import acceptance


def test_empty_artifact_cannot_pass():
    assert not acceptance([])['passed']


def test_calls_and_labels_are_not_execution_evidence():
    rows = [{'runner': 'pytest', 'deps_status': 'installed', 'model_requests': 1, 'telemetry': []}] * 3
    assert not acceptance(rows)['passed']


def test_collection_failure_cannot_manufacture_pair():
    rows = [{'runner': 'pytest', 'deps_status': 'installed', 'model_requests': 1,
             'telemetry': [{'head_outcome': 'error', 'base_outcome': 'pass', 'disposition': 'head_uncollectable'}]}] * 3
    assert not acceptance(rows)['passed']


def test_real_pair_with_healthy_dispositions_passes_smoke_only():
    rows = [{'runner': 'pytest', 'deps_status': 'installed', 'model_requests': 1,
             'telemetry': [{'head_outcome': 'fail', 'base_outcome': 'pass', 'disposition': 'catching'}]}] * 3
    assert acceptance(rows)['passed']
