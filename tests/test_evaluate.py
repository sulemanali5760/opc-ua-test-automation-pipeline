"""Unit tests for the spec evaluation logic — no PLC or network needed."""

from pathlib import Path

import pytest

from opcua_test_pipeline.client import evaluate, load_test_case, select_window

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

SHIPPED_CASES = sorted(p.name for p in (REPO / "examples").glob("TC-*.yaml"))


def test_there_are_shipped_test_cases_to_check():
    """Guard the glob below — an empty list would make it vacuously pass."""
    assert SHIPPED_CASES


@pytest.mark.parametrize("name", SHIPPED_CASES)
def test_shipped_test_cases_load_with_targets(name):
    tc = load_test_case(REPO / "examples" / name)
    assert tc["test_id"]
    assert tc["variable"] in tc["target"]["variables"]
    # node_path addresses a node in an OPC UA tree; ADS reads flat symbol
    # names and has no equivalent.
    if tc["target"].get("protocol") != "ads":
        assert tc["target"]["node_path"]


def test_condition_variable_is_also_sampled():
    """A test case must sample the variable its own condition depends on."""
    tc = load_test_case(REPO / "examples" / "TC-001_contactor_coil_voltage_sag.yaml")
    assert tc["condition_variable"] in tc["target"]["variables"]


# --- an unfinished test case must not report PASS ---------------------------

def test_spec_with_no_limits_is_refused():
    """A generated stub whose limits were never filled in checks nothing.

    Reporting PASS there would be indistinguishable from a real pass, so
    evaluate() refuses rather than rubber-stamping it.
    """
    stub = {"test_id": "TC-Stub", "variable": "CoilVoltage_V", "spec": {"units": "V"}}
    samples = [sample(0, CoilVoltage_V=18.0)]
    with pytest.raises(ValueError, match="neither spec.min nor spec.max"):
        evaluate(samples, stub)


def test_missing_spec_block_is_refused_too():
    stub = {"test_id": "TC-Stub", "variable": "CoilVoltage_V"}
    samples = [sample(0, CoilVoltage_V=18.0)]
    with pytest.raises(ValueError):
        evaluate(samples, stub)


# --- a typo in the test case must not look like a machine problem ----------------------------

def _write_case(tmp_path, **overrides):
    import yaml
    case = {"test_id": "TC-X", "title": "t", "variable": "CoilVoltage_V", "spec": {"min": 20.0}}
    case.update(overrides)
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(case), encoding="utf-8")
    return path


def test_misspelled_variable_is_refused(tmp_path):
    with pytest.raises(ValueError, match="CoilVoltge_V.*not in target.variables"):
        load_test_case(_write_case(tmp_path, variable="CoilVoltge_V"))


def test_misspelled_condition_variable_is_refused(tmp_path):
    with pytest.raises(ValueError, match="condition_variable"):
        load_test_case(_write_case(tmp_path, condition_variable="Current_A", condition_min=60.0))


def test_missing_limits_are_refused_even_without_data():
    """Before: a stub without limits and a run without matching samples came back as NO DATA."""
    with pytest.raises(ValueError, match="neither spec.min nor spec.max"):
        evaluate([], {"test_id": "TC-X", "variable": "CoilVoltage_V", "spec": {"units": "V"}})


def test_exit_codes_follow_the_verdict():
    from opcua_test_pipeline.client import exit_code
    assert (exit_code(True), exit_code(False), exit_code(None)) == (0, 1, 2)


# --- acquisition against a real OPC UA server started in the test ----------------------------

def test_samples_carry_measured_times_and_consistent_rows():
    import asyncio

    from asyncua import Server

    from opcua_test_pipeline.client import acquire

    endpoint = "opc.tcp://127.0.0.1:48471/plc/"
    target = {"namespace": "urn:test:plc", "node_path": ["Panel"], "variables": ["A", "B"]}

    async def go():
        server = Server()
        await server.init()
        server.set_endpoint(endpoint)
        idx = await server.register_namespace(target["namespace"])
        panel = await server.nodes.objects.add_object(idx, "Panel")
        await panel.add_variable(idx, "A", 1.5)
        await panel.add_variable(idx, "B", 7)
        async with server:
            return await acquire(endpoint, duration=1.0, hz=10, target=target, watch=["A"])
    run = asyncio.run(go())
    times = [s["t_s"] for s in run["samples"]]
    assert len(times) == 10 and times == sorted(times)
    assert 0.8 <= times[-1] <= 1.3                       # ten samples spread over about one second
    assert all((s["A"], s["B"]) == (1.5, 7) for s in run["samples"])
    assert run["late_samples"] == 0


# --- the installed command ----------------------------------------------------------------

def test_command_line_reports_a_bad_test_case_without_a_traceback(tmp_path, capsys):
    from opcua_test_pipeline.cli import main
    assert main(["run", str(_write_case(tmp_path, variable="Nope"))]) == 64
    assert "not in target.variables" in capsys.readouterr().err


def test_command_line_help_and_unknown_command(capsys):
    from opcua_test_pipeline.cli import main
    assert main([]) == 0 and "opcua-test run" not in capsys.readouterr().err
    assert main(["frobnicate"]) == 64


def test_report_command_writes_the_report(tmp_path):
    import json

    from opcua_test_pipeline.cli import main
    case = REPO / "examples" / "TC-002_panel_temperature_band.yaml"
    run = {"endpoint": "opc.tcp://x", "acquired_at_utc": "2026-01-01T00:00:00+00:00", "sample_hz": 1.0,
           "samples": [{"t_s": 0.0, "Temperature_C": 22.0}],
           "evaluation": {"TC-002": evaluate([{"t_s": 0.0, "Temperature_C": 22.0}], load_test_case(case))}}
    (tmp_path / "run.json").write_text(json.dumps(run), encoding="utf-8")
    assert main(["report", str(case), str(tmp_path / "run.json"), "--out", str(tmp_path / "r.md")]) == 0
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "**Verdict:** **PASS**" in text and "**Samples:** 1 at 1.0 Hz" in text
