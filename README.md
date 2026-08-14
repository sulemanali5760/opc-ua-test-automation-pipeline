# OPC UA Test Automation Pipeline

A small, runnable pipeline for pulling live process data off a PLC over
OPC UA, checking it against a written test-case spec, and generating a
pass/fail test report — instead of just eyeballing a trend chart.

It grew out of commissioning work on low-voltage protection panels, where
a chattering contactor on a high-current feeder turned out to be an
undersized control transformer: coil control voltage was sagging to ~18V
under an 80A inrush event against a 20V hold-in spec. That's the scenario
this repo models end-to-end — from a written hypothesis, to captured data,
to a generated report showing exactly where and by how much the spec was
missed.

## What it does

```
sim_plc_server.py  -->  opc_ua_client.py  -->  test_case_generator.py
(simulated PLC)         (acquire + check        (readable pass/fail
                          vs spec, save JSON)     Markdown report)
```

1. **`sim_plc_server.py`** — a simulated OPC UA server exposing the process
   variables you'd get off a real protection panel PLC (coil voltage,
   current draw, cycle time, temperature, pressure, contactor state, fault
   flag), replaying a scripted energise-under-inrush transient. Point
   `opc_ua_client.py` at a real PLC's endpoint instead and nothing else in
   the pipeline changes.
2. **`opc_ua_client.py`** — connects over OPC UA, samples the variables at
   1Hz for a set duration, evaluates them against a spec condition (e.g.
   "coil voltage must not drop below 20V while current draw exceeds 60A"),
   and saves the full run + verdict as JSON to `reports/`.
3. **`test_case_generator.py`** — takes a written test case
   (`test_cases/*.yaml`: hypothesis, procedure, expected result) and a
   captured run, and produces a Markdown test report with the actual
   verdict and evidence.

## Quickstart

```bash
pip install -r requirements.txt

# terminal 1
python sim_plc_server.py

# terminal 2 — sample for 15s, covering the energise transient at t=5s
python opc_ua_client.py --duration 15

# generate the readable report from the run you just captured
python test_case_generator.py test_cases/TC-001_contactor_coil_voltage_sag.yaml reports/run_<timestamp>.json
```

Expected result: `TC-001` reports **FAIL**, with the observed minimum coil
voltage (~18V) and the 20V spec floor both printed in the report.

## Project structure

```
sim_plc_server.py      simulated OPC UA PLC (swap for a real endpoint)
opc_ua_client.py        acquisition + spec-check client
test_case_generator.py  test case + run -> Markdown report
test_cases/              written test case definitions (YAML)
reports/                 generated run logs (JSON) and reports (Markdown)
```

## Why it's built this way

The point isn't the OPC UA plumbing — `asyncua` handles that. The point is
the shape of the workflow: a test case is a written hypothesis and a spec
*before* you run anything, the client's job is only to acquire data and
check it against that spec, and the report generator's job is to make the
verdict and evidence legible to someone who wasn't in the room. That
separation is what makes a test repeatable instead of a one-off debugging
session.

## Requirements

- Python 3.10+
- [`asyncua`](https://github.com/FreeOpcUa/opcua-asyncio) for the OPC UA
  client/server
- `pyyaml` for test case definitions
