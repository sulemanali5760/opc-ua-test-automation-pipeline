"""
OPC UA test-data acquisition client.

Connects to a PLC's OPC UA endpoint (simulated or real), polls a fixed set
of process variables at 1Hz for a configurable duration, and writes the
full sample log plus a spec-based pass/fail evaluation to reports/ as JSON.

Usage:
    python opc_ua_client.py --duration 15
    python opc_ua_client.py --endpoint opc.tcp://192.168.0.10:4840/plc/ --duration 30
    (real PLCs conventionally use the OPC UA default port 4840; this repo's
    simulator uses 4855 locally to avoid clashing with any OPC UA Local
    Discovery Server already running on your machine, e.g. from TIA Portal)

The JSON report this produces is consumed by test_case_generator.py to
produce a human-readable test report against a specific test case
definition (see test_cases/).
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from asyncua import Client

DEFAULT_ENDPOINT = "opc.tcp://localhost:4855/plc/"
NAMESPACE = "http://mbition-demo.local/plc"
VARIABLES = [
    "CoilVoltage_V",
    "CurrentDraw_A",
    "CycleTime_ms",
    "Temperature_C",
    "Pressure_mbar",
    "ContactorState",
    "FaultFlag",
]

REPORTS_DIR = Path(__file__).parent / "reports"


async def acquire(endpoint: str, duration: int, hz: float) -> dict:
    samples = []
    interval = 1.0 / hz

    async with Client(url=endpoint) as client:
        idx = await client.get_namespace_index(NAMESPACE)
        root = await client.nodes.objects.get_child([f"{idx}:ProtectionPanel"])
        var_nodes = {name: await root.get_child(f"{idx}:{name}") for name in VARIABLES}

        ticks = int(duration * hz)
        for i in range(ticks):
            t = round(i * interval, 3)
            row = {"t_s": t}
            for name, node in var_nodes.items():
                row[name] = await node.read_value()
            samples.append(row)
            print(f"t={t:5.2f}s  coil={row['CoilVoltage_V']:6.2f}V  "
                  f"current={row['CurrentDraw_A']:6.2f}A  state={row['ContactorState']}")
            await asyncio.sleep(interval)

    return {
        "endpoint": endpoint,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_hz": hz,
        "samples": samples,
    }


def evaluate_against_spec(run: dict, condition_variable: str, condition_min: float,
                           target_variable: str, spec_min: float) -> dict:
    windowed = [s for s in run["samples"] if s.get(condition_variable, 0) >= condition_min]
    if not windowed:
        return {"window_found": False, "passed": None, "min_observed": None}

    min_observed = min(s[target_variable] for s in windowed)
    return {
        "window_found": True,
        "window_samples": len(windowed),
        "min_observed": min_observed,
        "spec_min": spec_min,
        "passed": min_observed >= spec_min,
    }


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--duration", type=int, default=15, help="seconds to sample")
    parser.add_argument("--hz", type=float, default=1.0)
    parser.add_argument("--out", default=None, help="output JSON path (default: reports/run_<timestamp>.json)")
    args = parser.parse_args()

    run = await acquire(args.endpoint, args.duration, args.hz)

    run["evaluation"] = {
        "TC-001": evaluate_against_spec(
            run,
            condition_variable="CurrentDraw_A",
            condition_min=60.0,
            target_variable="CoilVoltage_V",
            spec_min=20.0,
        )
    }

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(run, indent=2), encoding="utf-8")

    verdict = run["evaluation"]["TC-001"]["passed"]
    print(f"\nSaved run log to {out_path}")
    print(f"TC-001 (coil voltage under inrush): {'PASS' if verdict else 'FAIL' if verdict is False else 'NO DATA'}")


if __name__ == "__main__":
    asyncio.run(main())
