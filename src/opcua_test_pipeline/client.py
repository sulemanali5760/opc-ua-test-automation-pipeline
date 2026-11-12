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
    opcua-test run examples/TC-001_contactor_coil_voltage_sag.yaml
    opcua-test run my_case.yaml --endpoint opc.tcp://192.168.0.10:4840/plc/ --duration 30
    (real PLCs conventionally use the OPC UA default port 4840; this repo's
    simulator uses 4855 locally to avoid clashing with any OPC UA Local
    Discovery Server already running on your machine, e.g. from TIA Portal)

The JSON this produces is consumed by `opcua-test report` to produce a
human-readable report against the same test case.
"""

import argparse
import asyncio
import json
import sys
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

REPORTS_DIR = Path("reports")   # in the folder the command is run from


def load_test_case(path) -> dict:
    """Read a test case YAML and fill in target defaults.

    A target declaring `protocol: ads` is left alone — the OPC UA defaults
    (namespace, node_path) mean nothing to ADS and merging them in would only
    produce confusing keys.
    """
    test_case = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    declared = test_case.get("target") or {}
    if declared.get("protocol") == "ads":
        target = declared
    else:
        target = dict(DEFAULT_TARGET)
        target.update(declared)
    test_case["target"] = target
    # A misspelled name would otherwise be sampled as "never there" and reported as NO DATA,
    # which reads like a problem with the machine instead of a typo in the test case.
    for key in ("variable", "condition_variable"):
        name = test_case.get(key)
        if name and name not in target.get("variables", []):
            raise ValueError(
                f"test case {test_case.get('test_id', '?')}: {key} {name!r} is not in target.variables "
                f"({', '.join(target.get('variables', [])) or 'empty'}), so it would never be sampled."
            )
    return test_case


def exit_code(passed) -> int:
    """0 = PASS, 1 = FAIL, 2 = NO DATA, so a script or CI job can act on the verdict."""
    return 0 if passed else 1 if passed is False else 2


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
    if spec_min is None and spec_max is None:
        # An unfinished test case — a generated stub whose limits were never
        # filled in, say. Reporting PASS here would mean "nothing was checked"
        # and look identical to a real pass, so refuse instead.
        raise ValueError(
            f"test case {test_case.get('test_id', '?')} sets neither spec.min "
            "nor spec.max, so there is nothing to check. Fill in a limit."
        )

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
        names = list(target["variables"])
        var_nodes = [await node.get_child(f"{idx}:{name}") for name in names]

        # Sample on a fixed schedule and record the time each sample was really taken. One request
        # reads all variables, so the values of a row belong together. If the server cannot answer
        # fast enough the schedule slips; the recorded times show it and late_samples counts it.
        loop = asyncio.get_running_loop()
        start = loop.time()
        late = 0
        for i in range(int(duration * hz)):
            due = start + i * interval
            delay = due - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            elif delay < -interval / 2:
                late += 1
            values = await client.read_values(var_nodes)
            t = round(loop.time() - start, 3)
            row = {"t_s": t, **dict(zip(names, values))}
            samples.append(row)
            trace = "  ".join(f"{name}={row[name]}" for name in watch)
            print(f"t={t:6.2f}s  {trace}")

    return {
        "endpoint": endpoint,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_hz": hz,
        "late_samples": late,
        "samples": samples,
    }


async def main(argv=None):
    parser = argparse.ArgumentParser(prog="opcua-test run", description="Sample the variables of a test case "
                                     "and check them against its limits. Exit code: 0 PASS, 1 FAIL, 2 NO DATA.")
    parser.add_argument("test_case", help="path to a test case YAML (see examples/)")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--duration", type=float, default=15, help="seconds to sample")
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--out", default=None,
                        help="output JSON path (default: reports/run_<timestamp>.json)")
    args = parser.parse_args(argv)

    test_case = load_test_case(args.test_case)
    test_id = test_case["test_id"]
    target = test_case["target"]
    watch = [test_case["variable"], test_case.get("condition_variable")]

    # The protocol is a property of the machine, so it lives in the test case
    # rather than on the command line. Everything after this point is identical
    # either way — that is the whole point of keeping evaluate() pure.
    if target.get("protocol") == "ads":
        from opcua_test_pipeline import ads
        run = ads.acquire(target, args.duration, args.hz, watch=watch)
    else:
        run = await acquire(args.endpoint, args.duration, args.hz, target,
                            watch=watch)
    run["evaluation"] = {test_id: evaluate(run["samples"], test_case)}

    out_path = Path(args.out) if args.out else \
        REPORTS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(run, indent=2), encoding="utf-8")

    passed = run["evaluation"][test_id]["passed"]
    verdict = "PASS" if passed else "FAIL" if passed is False else "NO DATA"
    print(f"\nSaved run log to {out_path}")
    print(f"{test_id} ({test_case['title']}): {verdict}")
    if run.get("late_samples"):
        print(f"warning: {run['late_samples']} sample(s) were taken late; the server could not keep up with "
              f"{args.hz} Hz. The recorded times are the real ones.")
    return exit_code(passed)


def run(argv=None) -> int:
    return asyncio.run(main(argv))


if __name__ == "__main__":
    sys.exit(run())
