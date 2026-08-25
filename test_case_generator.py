"""
Generates a human-readable Markdown test report from a test case definition
(test_cases/*.yaml) and a captured run log (reports/run_*.json produced by
opc_ua_client.py).

This is the piece that turns a raw data pull into something a reviewer can
read in thirty seconds: hypothesis, procedure, expected result, and the
actual observed pass/fail with the evidence.

Usage:
    python test_case_generator.py test_cases/TC-001_contactor_coil_voltage_sag.yaml reports/run_20260101_120000.json
"""

import argparse
import json
from pathlib import Path

import yaml


def generate_report(test_case: dict, run: dict) -> str:
    test_id = test_case["test_id"]
    evaluation = run.get("evaluation", {}).get(test_id)

    if evaluation is None or evaluation["passed"] is None:
        verdict = "NO DATA — condition window never occurred in this run"
    elif evaluation["passed"]:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    lines = [
        f"# Test Report: {test_id} — {test_case['title']}",
        "",
        f"**Author:** {test_case.get('author', 'unknown')}",
        f"**Run acquired:** {run['acquired_at_utc']}",
        f"**Endpoint:** {run['endpoint']}",
        f"**Verdict:** **{verdict}**",
        "",
        "## Hypothesis",
        test_case["hypothesis"].strip(),
        "",
        "## Procedure",
    ]
    for step in test_case["procedure"]:
        lines.append(f"- {step}")

    lines += [
        "",
        "## Expected Result",
        test_case["expected_result"].strip(),
        "",
        "## Observed Result",
    ]

    if evaluation and evaluation["window_found"]:
        units = test_case.get("spec", {}).get("units", "")
        variable = test_case["variable"]
        condition_variable = test_case.get("condition_variable")

        if condition_variable:
            lines.append(
                f"- Condition window (`{condition_variable} >= "
                f"{test_case['condition_min']}`): {evaluation['window_samples']} samples"
            )
        else:
            lines.append(f"- Evaluated over the whole run: {evaluation['window_samples']} samples")

        if evaluation["spec_min"] is not None:
            lines.append(
                f"- Minimum `{variable}` observed: "
                f"**{evaluation['min_observed']:.2f} {units}** "
                f"(spec floor {evaluation['spec_min']} {units})"
            )
        if evaluation["spec_max"] is not None:
            lines.append(
                f"- Maximum `{variable}` observed: "
                f"**{evaluation['max_observed']:.2f} {units}** "
                f"(spec ceiling {evaluation['spec_max']} {units})"
            )

        if not evaluation["passed"]:
            if evaluation["spec_min"] is not None and evaluation["min_observed"] < evaluation["spec_min"]:
                margin = evaluation["spec_min"] - evaluation["min_observed"]
                lines.append(f"- **{margin:.2f} {units} below the spec floor**")
            if evaluation["spec_max"] is not None and evaluation["max_observed"] > evaluation["spec_max"]:
                margin = evaluation["max_observed"] - evaluation["spec_max"]
                lines.append(f"- **{margin:.2f} {units} above the spec ceiling**")
            note = test_case.get("on_failure")
            if note:
                lines.append(f"- {note.strip()}")
    else:
        lines.append("- Condition window never occurred during this run — re-run with a longer duration.")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("test_case_yaml")
    parser.add_argument("run_json")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    test_case = yaml.safe_load(Path(args.test_case_yaml).read_text(encoding="utf-8"))
    run = json.loads(Path(args.run_json).read_text(encoding="utf-8"))

    report = generate_report(test_case, run)

    out_path = Path(args.out) if args.out else Path(args.run_json).with_suffix(".report.md")
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved report to {out_path}")


if __name__ == "__main__":
    main()
