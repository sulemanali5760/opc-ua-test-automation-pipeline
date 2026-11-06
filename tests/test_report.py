"""The report generator must read a test case the same way evaluate() does."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_case_generator import generate_report  # noqa: E402


def test_report_uses_zero_when_condition_threshold_is_implicit():
    """evaluate() defaults condition_min to 0.0, so the report must too.

    A test case can name a condition variable without a threshold; the run
    then treats ">= 0" as the window. The report must describe that window
    instead of failing with a KeyError on condition_min.
    """
    test_case = {
        "test_id": "TC-004",
        "title": "Motor current while running",
        "author": "Suleman Ali",
        "hypothesis": "Current stays inside its band whenever the drive runs.",
        "procedure": ["Run the drive and sample the current."],
        "variable": "Current_A",
        "condition_variable": "Running",
        "spec": {"min": 0.0, "max": 10.0, "units": "A"},
        "expected_result": "Current_A stays between 0 A and 10 A while Running.",
    }
    run = {
        "acquired_at_utc": "2026-11-06T00:00:00+00:00",
        "endpoint": "opc.tcp://example:4840/plc/",
        "evaluation": {
            "TC-004": {
                "window_found": True,
                "window_samples": 2,
                "min_observed": 1.0,
                "max_observed": 2.0,
                "spec_min": 0.0,
                "spec_max": 10.0,
                "passed": True,
            }
        },
    }

    report = generate_report(test_case, run)

    assert "`Running >= 0.0`" in report
    assert "2 samples" in report
