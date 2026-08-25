"""Unit tests for the spec evaluation logic — no PLC or network needed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opc_ua_client import evaluate, load_test_case, select_window  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def sample(t, **kw):
    return {"t_s": t, **kw}


# --- select_window ----------------------------------------------------------

def test_window_is_whole_run_when_no_condition():
    samples = [sample(0, V=24.0), sample(1, V=23.0)]
    assert len(select_window(samples, None, 0.0)) == 2


def test_window_filters_on_condition_threshold():
    samples = [sample(0, A=10.0), sample(1, A=70.0), sample(2, A=65.0), sample(3, A=5.0)]
    assert len(select_window(samples, "A", 60.0)) == 2


def test_window_ignores_non_numeric_samples():
    samples = [sample(0, A=None), sample(1, A="OPEN"), sample(2, A=70.0)]
    assert len(select_window(samples, "A", 60.0)) == 1


# --- evaluate: minimum spec -------------------------------------------------

MIN_CASE = {
    "variable": "CoilVoltage_V",
    "condition_variable": "CurrentDraw_A",
    "condition_min": 60.0,
    "spec": {"min": 20.0},
}


def test_fails_when_value_sags_below_floor_inside_window():
    samples = [
        sample(0, CoilVoltage_V=24.0, CurrentDraw_A=0.0),    # outside window
        sample(1, CoilVoltage_V=18.0, CurrentDraw_A=80.0),   # inside, below spec
        sample(2, CoilVoltage_V=24.0, CurrentDraw_A=4.5),    # outside window
    ]
    result = evaluate(samples, MIN_CASE)
    assert result["passed"] is False
    assert result["min_observed"] == 18.0
    assert result["window_samples"] == 1


def test_passes_when_value_holds_inside_window():
    samples = [
        sample(0, CoilVoltage_V=23.0, CurrentDraw_A=80.0),
        sample(1, CoilVoltage_V=22.5, CurrentDraw_A=70.0),
    ]
    assert evaluate(samples, MIN_CASE)["passed"] is True


def test_a_sag_outside_the_window_does_not_fail_the_test():
    """The window is the point: a dip while the machine is idle is not a breach."""
    samples = [
        sample(0, CoilVoltage_V=12.0, CurrentDraw_A=0.0),   # low, but outside window
        sample(1, CoilVoltage_V=23.0, CurrentDraw_A=80.0),
    ]
    assert evaluate(samples, MIN_CASE)["passed"] is True


def test_no_data_verdict_when_window_never_occurs():
    samples = [sample(0, CoilVoltage_V=24.0, CurrentDraw_A=1.0)]
    result = evaluate(samples, MIN_CASE)
    assert result["passed"] is None
    assert result["window_found"] is False


# --- evaluate: band spec ----------------------------------------------------

BAND_CASE = {"variable": "Temperature_C", "spec": {"min": 15.0, "max": 30.0}}


@pytest.mark.parametrize(
    "temps, expected",
    [
        ([22.0, 21.8, 22.3], True),    # inside the band
        ([22.0, 34.0], False),          # over the ceiling
        ([22.0, 9.0], False),           # under the floor
        ([15.0, 30.0], True),           # limits are inclusive
    ],
)
def test_band_spec(temps, expected):
    samples = [sample(i, Temperature_C=v) for i, v in enumerate(temps)]
    assert evaluate(samples, BAND_CASE)["passed"] is expected


# --- the shipped test cases stay loadable and correctly wired ---------------

@pytest.mark.parametrize("name", [
    "TC-001_contactor_coil_voltage_sag.yaml",
    "TC-002_panel_temperature_band.yaml",
])
def test_shipped_test_cases_load_with_targets(name):
    tc = load_test_case(REPO / "test_cases" / name)
    assert tc["test_id"]
    assert tc["variable"] in tc["target"]["variables"]
    assert tc["target"]["node_path"]


def test_condition_variable_is_also_sampled():
    """A test case must sample the variable its own condition depends on."""
    tc = load_test_case(REPO / "test_cases" / "TC-001_contactor_coil_voltage_sag.yaml")
    assert tc["condition_variable"] in tc["target"]["variables"]
