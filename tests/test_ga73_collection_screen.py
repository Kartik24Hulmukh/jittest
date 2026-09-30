from eval.ga73_collection import collection_screen
from eval.ga73_smoke import acceptance


def test_model_refusals_do_not_dilute_oracle_failures():
    telemetry = ([{"disposition": "model_declined"}] * 49
                 + [{"disposition": "head_uncollectable", "head_outcome": "uncollectable"}] * 10
                 + [{"disposition": "head_failed_base_failed_latent", "head_outcome": "fail", "base_outcome": "fail"}])
    screen = collection_screen(telemetry)
    assert screen["oracle_entering_candidates"] == 11
    assert screen["healthy_collection"] is False
    rows = [{"runner": "pytest", "deps_status": "installed", "model_requests": 1,
             "telemetry": telemetry},
            {"runner": "pytest", "deps_status": "installed", "model_requests": 1, "telemetry": []},
            {"runner": "pytest", "deps_status": "installed", "model_requests": 1, "telemetry": []}]
    assert acceptance(rows)["passed"] is False


def test_missing_outcome_for_uncollectable_refuses():
    assert collection_screen([{"disposition": "head_uncollectable"}])["healthy_collection"] is False


def test_only_generation_refusals_are_not_measured_collection():
    result = collection_screen([{"disposition": "model_declined"}] * 100)
    assert result["healthy_collection"] is False
    assert result["oracle_entering_candidates"] == 0


def test_twenty_percent_boundary_and_strictly_lower_threshold():
    good = {"disposition": "non_discriminating", "head_outcome": "pass", "base_outcome": "pass"}
    bad = {"disposition": "head_uncollectable", "head_outcome": "uncollectable"}
    assert collection_screen([good] * 4 + [bad])["healthy_collection"] is False
    assert collection_screen([good] * 5 + [bad])["healthy_collection"] is True


def test_empty_or_malformed_screen_fails_closed():
    assert collection_screen([])["healthy_collection"] is False
    assert collection_screen([None])["healthy_collection"] is False
