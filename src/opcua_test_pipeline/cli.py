"""opcua-test run CASE.yaml | opcua-test report CASE.yaml RUN.json | opcua-test sim"""
import sys

USAGE = """usage: opcua-test <command> [options]

commands:
  run CASE.yaml [--endpoint URL] [--duration S] [--hz N] [--out FILE]
        sample the PLC and check the test case; exit code 0 PASS, 1 FAIL, 2 NO DATA
  report CASE.yaml RUN.json [--out FILE]
        write the Markdown test report for a captured run
  sim   start the bundled simulated PLC on opc.tcp://127.0.0.1:4855/plc/

add --help after a command for its options"""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    command, rest = argv[0], argv[1:]
    if command == "run":
        from opcua_test_pipeline.client import run
    elif command == "report":
        from opcua_test_pipeline.report import main as run
    elif command == "sim":
        from opcua_test_pipeline.sim import run
    else:
        print(f"opcua-test: unknown command {command!r}\n\n{USAGE}", file=sys.stderr)
        return 64
    try:
        return run(rest)
    except (ValueError, FileNotFoundError) as e:   # a bad test case or path: say it, no traceback
        print(f"opcua-test: {e}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    sys.exit(main())
