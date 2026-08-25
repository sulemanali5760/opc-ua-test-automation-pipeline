"""ADS target parsing is pure, so it tests without TwinCAT or a PLC.

The acquisition itself needs a live ADS router and is not covered here — CI
has no TwinCAT. What is covered is everything that can be got wrong before a
connection is attempted, which is where the confusing failures live.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ads_backend  # noqa: E402
from opc_ua_client import load_test_case  # noqa: E402

GOOD = {
    "protocol": "ads",
    "ams_net_id": "5.85.146.11.1.1",
    "ams_port": 851,
    "variables": ["MAIN.fbMachine.fbHandling.fbCycle.Step"],
}


def test_resolves_a_complete_target():
    net_id, port, variables = ads_backend.resolve_target(GOOD)
    assert net_id == "5.85.146.11.1.1"
    assert port == 851
    assert variables == ["MAIN.fbMachine.fbHandling.fbCycle.Step"]


def test_ams_port_defaults_to_the_twincat3_runtime():
    target = {k: v for k, v in GOOD.items() if k != "ams_port"}
    _, port, _ = ads_backend.resolve_target(target)
    assert port == ads_backend.DEFAULT_AMS_PORT == 851


def test_missing_net_id_is_refused_with_a_useful_message():
    target = {k: v for k, v in GOOD.items() if k != "ams_net_id"}
    with pytest.raises(ValueError, match="ams_net_id is required"):
        ads_backend.resolve_target(target)


@pytest.mark.parametrize("bad", ["192.168.0.10", "5.85.146.11.1", "not-an-id",
                                 "5.85.146.11.1.1.1"])
def test_a_net_id_that_is_really_an_ip_is_caught_early(bad):
    """An IP where an AMS NetId belongs otherwise fails as an opaque ADS code."""
    with pytest.raises(ValueError, match="does not look like an AMS NetId"):
        ads_backend.resolve_target({**GOOD, "ams_net_id": bad})


def test_empty_variable_list_is_refused():
    with pytest.raises(ValueError, match="variables is empty"):
        ads_backend.resolve_target({**GOOD, "variables": []})


# --- the ADS target must not be polluted by OPC UA defaults -----------------

def test_ads_target_does_not_inherit_opcua_defaults():
    """DEFAULT_TARGET's namespace/node_path are meaningless over ADS."""
    case = load_test_case(
        Path(__file__).parents[1] / "test_cases" / "TC-003_pickplace_cycle_time.yaml")
    target = case["target"]
    assert target["protocol"] == "ads"
    assert "namespace" not in target
    assert "node_path" not in target


def test_shipped_ads_case_resolves():
    case = load_test_case(
        Path(__file__).parents[1] / "test_cases" / "TC-003_pickplace_cycle_time.yaml")
    net_id, port, variables = ads_backend.resolve_target(case["target"])
    assert port == 851
    assert case["variable"] in variables
