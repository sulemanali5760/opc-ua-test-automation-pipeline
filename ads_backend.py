"""Beckhoff ADS acquisition backend.

Same job as the OPC UA client — sample a machine's variables over time — but
speaking ADS, TwinCAT's native protocol, instead.

Why bother when OPC UA is the open standard: on Beckhoff kit the OPC UA server
(TF6100) is a separately licensed function, so on a lot of real machines it is
simply not switched on. ADS is always there, needs no licence, and needs no
certificate exchange. If you can see the PLC in TwinCAT, you can read it here.

The trade-off is that this only works on Beckhoff. Everything downstream —
evaluate(), the report generator, the test case format — is unchanged, which
is the point: the protocol is a detail, the spec check is the program.

pyads is an optional dependency. It is imported inside acquire() so that the
OPC UA path keeps working on a machine that has never heard of TwinCAT.
"""

import time
from datetime import datetime, timezone

# TwinCAT 3 runtime; TwinCAT 2 used 801.
DEFAULT_AMS_PORT = 851

_PYADS_MISSING = (
    "This test case uses protocol: ads, which needs the pyads package.\n"
    "  pip install pyads\n"
    "pyads talks to the TwinCAT ADS router, so it also needs TwinCAT (or the\n"
    "Beckhoff ADS runtime) installed on this machine. On Linux, see\n"
    "https://github.com/stlehmann/pyads for the adslib build step."
)


def resolve_target(target: dict) -> tuple:
    """Pull the ADS connection details out of a test case target block.

    Pure — no connection is made. Returns (ams_net_id, ams_port, variables).
    Raises ValueError with an actionable message when something is missing,
    because a bad AMS NetId otherwise surfaces as an opaque ADS error code.
    """
    net_id = target.get("ams_net_id")
    if not net_id:
        raise ValueError(
            "target.ams_net_id is required for protocol: ads — it is the "
            "PLC's AMS NetId, e.g. 5.85.146.11.1.1. TwinCAT shows it under "
            "the router's local settings, or in the target list."
        )
    if net_id.count(".") != 5:
        raise ValueError(
            f"target.ams_net_id {net_id!r} does not look like an AMS NetId. "
            "It has six dot-separated parts, e.g. 5.85.146.11.1.1 — usually "
            "the PLC's IP with '.1.1' appended."
        )

    variables = target.get("variables") or []
    if not variables:
        raise ValueError(
            "target.variables is empty — list the symbol names to sample, "
            "e.g. MAIN.fbMachine.fbHandling.fbLift.bExtendCoil"
        )

    return net_id, int(target.get("ams_port", DEFAULT_AMS_PORT)), list(variables)


def acquire(target: dict, duration: float, hz: float, watch: list = None) -> dict:
    """Sample the target's variables over ADS and return a run log.

    Shape of the return value matches the OPC UA client's acquire() exactly,
    so evaluate() and the report generator cannot tell the difference.
    """
    try:
        import pyads
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise SystemExit(_PYADS_MISSING) from exc

    net_id, port, variables = resolve_target(target)
    watch = [v for v in (watch or []) if v in variables]
    interval = 1.0 / hz
    samples = []

    plc = pyads.Connection(net_id, port)
    plc.open()
    try:
        if not plc.is_open:  # pragma: no cover - needs a live router
            raise SystemExit(
                f"opened a connection to {net_id}:{port} but it is not live. "
                "Check the PLC is in Run and that a route to it exists."
            )

        for i in range(int(duration * hz)):
            t = round(i * interval, 3)
            row = {"t_s": t}
            for name in variables:
                row[name] = plc.read_by_name(name)
            samples.append(row)
            trace = "  ".join(f"{name}={row[name]}" for name in watch)
            print(f"t={t:6.2f}s  {trace}")
            time.sleep(interval)
    finally:
        plc.close()

    return {
        "endpoint": f"ads://{net_id}:{port}",
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_hz": hz,
        "samples": samples,
    }
