"""Check live PLC data against a written test case and report PASS, FAIL or NO DATA."""
from opcua_test_pipeline.client import evaluate, exit_code, load_test_case, select_window
from opcua_test_pipeline.report import generate_report

__version__ = "0.2.0"
__all__ = ["evaluate", "exit_code", "generate_report", "load_test_case", "select_window"]
