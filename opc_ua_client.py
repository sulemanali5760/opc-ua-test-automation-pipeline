"""
OPC UA test-data acquisition client.

Connects to a PLC's OPC UA endpoint (simulated or real), samples the process
variables named by a test case, and writes the full sample log plus a
spec-based pass/fail evaluation to reports/ as JSON.

Everything specific to a machine lives in the test case file, not in here:
which node to browse, which variables to sample, the condition that defines
the window of interest, and the spec the variable must hold to. Point this at
your own PLC with your own test case and nothing in this file needs editing.

Usage:
    python opc_ua_client.py --test-case test_cases/TC-001_contactor_coil_voltage_sag.yaml
    python opc_ua_client.py --test-case my_case.yaml --endpoint opc.tcp://192.168.0.10:4840/plc/ --duration 30
    (real PLCs conventionally use the OPC UA default port 4840; this repo's
    simulator uses 4855 locally to avoid clashing with any OPC UA Local
    Discovery Server already running on your machine, e.g. from TIA Portal)

The JSON this produces is consumed by test_case_generator.py to produce a
human-readable report against the same test case.
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml
from asyncua import Client

DEFAULT_ENDPOINT = "opc.tcp://localhost:4855/plc/"

# Used only when a test case does not declare its own `target:` block.
DEFAULT_TARGET = {
    "namespace": "http://panel-demo.local/plc",
    "node_path": ["ProtectionPanel"],
    "variables": [
        "CoilVoltage_V",
        "CurrentDraw_A",
        "CycleTime_ms",
        "Temperature_C",
        "Pressure_mbar",
        "ContactorState",
        "FaultFlag",
    ],
}

REPORTS_DIR = Path(__file__).parent / "reports"


def load_test_case(path) -> dict:
    """Read a test case YAML and fill in target defaults."""
    test_case = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    target = dict(DEFAULT_TARGET)
    target.update(test_case.get("target") or {})
    test_case["target"] = target
    return test_case


def select_window(samples: list, condition_variable, condition_min) -> list:
    """The samples a test case cares about.

    A test case with no condition_variable is evaluated over the whole run;
    otherwise only samples where the condition variable reaches condition_min
    count, which is what isolates a transient such as an inrush event.
    """
    if not condition_variable:
        return list(samples)
    return [
        s for s in samples
        if isinstance(s.get(condition_variable), (int, float))
        and s[condition_variable] >= condition_min
    ]


def evaluate(samples: list, test_case: dict) -> dict:
    """Check a run against a test case spec. Pure function — no I/O.

    Returns passed=None when the condition window never occurred, which is a
    different outcome from a failure and is reported as such.
    """
    variable = test_case["variable"]
    spec = test_case.get("spec") or {}
    spec_min = spec.get("min")
    spec_max = spec.get("max")

    window = select_window(
        samples,
        test_case.get("condition_variable"),
        test_case.get("condition_min", 0.0),
    )
    values = [s[variable] for s in window if isinstance(s.get(variable), (int, float))]

    if not values:
        return {
            "window_found": False,
            "window_samples": 0,
            "min_observed": None,
            "max_observed": None,
            "spec_min": spec_min,
            "spec_max": spec_max,
            "passed": None,
        }

    min_observed = min(values)
    max_observed = max(values)

    if spec_min is None and spec_max is None:
        # An unfinished test case — a generated stub whose limits were never
        # filled in, say. Reporting PASS here would mean "nothing was checked"
        # and look identical to a real pass, so refuse instead.
        raise ValueError(
            f"test case {test_case.get('test_id', '?')} sets neither spec.min "
            "nor spec.max, so there is nothing to check. Fill in a limit."
        )

    passed = True
    if spec_min is not None:
        passed = passed and min_observed >= spec_min
    if spec_max is not None:
        passed = passed and max_observed <= spec_max

    return {
        "window_found": True,
        "window_samples": len(window),
        "min_observed": min_observed,
        "max_observed": max_observed,
        "spec_min": spec_min,
        "spec_max": spec_max,
        "passed": passed,
    }


async def acquire(endpoint: str, duration: float, hz: float, target: dict,
                  watch: list = None) -> dict:
    samples = []
    interval = 1.0 / hz
    watch = [v for v in (watch or []) if v in target["variables"]]

    async with Client(url=endpoint) as client:
        idx = await client.get_namespace_index(target["namespace"])
        node = client.nodes.objects
        for name in target["node_path"]:
            node = await node.get_child(f"{idx}:{name}")
        var_nodes = {name: await node.get_child(f"{idx}:{name}")
                     for name in target["variables"]}

        for i in range(int(duration * hz)):
            t = round(i * interval, 3)
            row = {"t_s": t}
            for name, var_node in var_nodes.items():
                row[name] = await var_node.read_value()
            samples.append(row)
            trace = "  ".join(f"{name}={row[name]}" for name in watch)
            print(f"t={t:6.2f}s  {trace}")
            await asyncio.sleep(interval)

    return {
        "endpoint": endpoint,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_hz": hz,
        "samples": samples,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-case", required=True,
                        help="path to a test case YAML (see test_cases/)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--duration", type=float, default=15, help="seconds to sample")
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--out", default=None,
                        help="output JSON path (default: reports/run_<timestamp>.json)")
    args = parser.parse_args()

    test_case = load_test_case(args.test_case)
    test_id = test_case["test_id"]

    run = await acquire(
        args.endpoint, args.duration, args.hz, test_case["target"],
        watch=[test_case["variable"], test_case.get("condition_variable")],
    )
    run["evaluation"] = {test_id: evaluate(run["samples"], test_case)}

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else \
        REPORTS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(run, indent=2), encoding="utf-8")

    passed = run["evaluation"][test_id]["passed"]
    verdict = "PASS" if passed else "FAIL" if passed is False else "NO DATA"
    print(f"\nSaved run log to {out_path}")
    print(f"{test_id} ({test_case['title']}): {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
