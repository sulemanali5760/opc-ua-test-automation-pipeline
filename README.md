# OPC UA Test Automation Pipeline

[![CI](https://github.com/sulemanali5760/opc-ua-test-automation-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/sulemanali5760/opc-ua-test-automation-pipeline/actions/workflows/ci.yml)

### ▶ [Watch it run in your browser](https://sulemanali5760.github.io/opc-ua-test-automation-pipeline/)

No install. The fault happens, the tool measures it, and the verdict appears —
live, on simulated data. Drag the transformer slider to turn the FAIL into a
PASS and watch why.

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
opcua-test sim   -->   opcua-test run   -->   opcua-test report
(simulated PLC)        (acquire + check       (readable pass/fail
                        vs spec, save JSON)    Markdown report)
```

1. **`opcua-test sim`** — a simulated OPC UA server exposing the process
   variables you'd get off a real protection panel PLC (coil voltage,
   current draw, cycle time, temperature, pressure, contactor state, fault
   flag), replaying a scripted energise-under-inrush transient. Point
   `opcua-test run` at a real PLC's endpoint instead and nothing else in
   the pipeline changes.
2. **`opcua-test run`** — connects over OPC UA, samples the variables at
   1Hz (all in one request per sample, with the measured sample time) for a set duration, evaluates them against a spec condition (e.g.
   "coil voltage must not drop below 20V while current draw exceeds 60A"),
   and saves the full run + verdict as JSON to `reports/`.
3. **`opcua-test report`** — takes a written test case
   (`examples/*.yaml`: hypothesis, procedure, expected result) and a
   captured run, and produces a Markdown test report with the actual
   verdict and evidence.

## Install

With internet:

```bash
pip install https://github.com/sulemanali5760/opc-ua-test-automation-pipeline/releases/download/v0.2.0/opcua_test_pipeline-0.2.0-py3-none-any.whl
```

Without internet (a plant PC, a commissioning laptop on the machine network): download the offline bundle
for your system from the [latest release](https://github.com/sulemanali5760/opc-ua-test-automation-pipeline/releases/latest), carry
it over on a USB stick, unzip it and run inside the folder:

```bash
python -m pip install --no-index --find-links . opcua-test-pipeline
```

The bundle holds this tool and every package it needs; nothing is downloaded. Each bundle is installed in a
clean environment and started once before it is published. Python 3.11 or newer. Not on PyPI yet.

For Beckhoff ADS add `pyads` (`pip install pyads`); it is not part of the bundle because it needs the TwinCAT ADS router.

## Quickstart

```bash
# terminal 1
opcua-test sim

# terminal 2 — sample for 15s, covering the energise transient at t=5s
opcua-test run examples/TC-001_contactor_coil_voltage_sag.yaml --duration 15

# generate the readable report from the run you just captured
opcua-test report examples/TC-001_contactor_coil_voltage_sag.yaml reports/run_<timestamp>.json
```

Run logs and reports are written to `reports/` in the folder you run the command from.

Expected result: `TC-001` reports **FAIL**, with the observed minimum coil
voltage (~18V) and the 20V spec floor both printed in the report. Run
`TC-002` the same way and it reports **PASS** — both verdicts are asserted
in CI on every push.

## Point it at your own machine

Nothing machine-specific lives in the Python. A test case declares what to
connect to and what to check, so using this on your own PLC means writing one
YAML file — no code changes:

```yaml
test_id: TC-010
title: Spindle bearing temperature under continuous cut
author: you
hypothesis: >
  Bearing temperature stays inside its rating during a 30-minute cut.
procedure:
  - Run the spindle at 8000 rpm for 30 minutes and sample throughout.
variable: BearingTemp_C
condition_variable: SpindleSpeed_rpm   # optional — omit to evaluate the whole run
condition_min: 7500.0
spec:
  max: 80.0        # `min`, `max`, or both
  units: C
expected_result: >
  BearingTemp_C never exceeds 80C while the spindle is above 7500 rpm.
on_failure: >
  Check lubrication and bearing preload.        # optional note, shown on FAIL

target:                                  # optional — defaults to this repo's simulator
  namespace: http://your-plc.local/plc
  node_path: [Machine, Spindle]          # browse path under Objects
  variables: [BearingTemp_C, SpindleSpeed_rpm]
```

Then:

```bash
opcua-test run my_case.yaml --endpoint opc.tcp://192.168.0.10:4840/plc/ --duration 1800 --hz 0.5
```

`condition_variable` is what makes a test meaningful on a running machine: it
isolates the window you actually care about, so a reading that dips while the
machine is idle does not fail a test about behaviour under load.

## Verdict as exit code

`opcua-test run` exits with 0 for PASS, 1 for FAIL and 2 for NO DATA (the
condition window never occurred), so a script or a CI job can act on the result
without reading the report.

## Limits

- **Polling sees slow events only.** The client reads the PLC once per sample
  (default 1 Hz, a few Hz at most over OPC UA). Anything shorter than about two
  sample periods can be missed completely. A real contactor inrush lasts tens of
  milliseconds; the simulator stretches the sag to two seconds so that the
  workflow can be shown. On a real machine, let the PLC capture the fast event
  (latch the minimum, or record a buffer in a fast task) and check that latched
  value with a test case here.
- **Few samples in the window means weak evidence.** The report prints how many
  samples the verdict rests on. One sample is a hint, not a measurement.
- **Sample times are the client's clock.** Each row carries the time it was
  really read; if the server answers too slowly, the run log counts the late samples.
- **No security.** The client connects anonymously without encryption. A PLC
  that requires a certificate or a login cannot be read yet; to see what such a
  server asks for, use [opcua-doctor](https://github.com/sulemanali5760/opcua-doctor).
- **ADS path not run in CI.** The Beckhoff backend is unit-tested without a
  controller; reading a real TwinCAT runtime needs one.
- **One variable against fixed limits.** No rate-of-change, no comparison of two
  signals, no statistics.

## Project structure

```
src/opcua_test_pipeline/
  cli.py                the opcua-test command
  client.py             acquisition + spec check
  report.py             test case + run -> Markdown report
  ads.py                Beckhoff ADS acquisition
  sim.py                simulated OPC UA PLC
examples/               written test case definitions (YAML)
tests/                  unit tests, live acquisition test, command-line tests
.github/workflows/      CI: tests + end-to-end run against the simulator; release: wheel + offline bundles
```

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

The unit tests cover the evaluation logic with no PLC or network involved.
CI additionally runs the real pipeline against the bundled simulator and
asserts that TC-001 comes back FAIL and TC-002 comes back PASS — if the
chain ever stops working, the badge goes red.

## Why it's built this way

The point isn't the OPC UA plumbing — `asyncua` handles that. The point is
the shape of the workflow: a test case is a written hypothesis and a spec
*before* you run anything, the client's job is only to acquire data and
check it against that spec, and the report generator's job is to make the
verdict and evidence legible to someone who wasn't in the room. That
separation is what makes a test repeatable instead of a one-off debugging
session.

## Requirements

- Python 3.11+
- [`asyncua`](https://github.com/FreeOpcUa/opcua-asyncio) for the OPC UA
  client/server
- `pyyaml` for test case definitions

## Licence

MIT — see [LICENSE](LICENSE). Use it, change it, ship it.
