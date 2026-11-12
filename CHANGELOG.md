# Changelog

All notable changes to this project are listed here. Versions follow [Semantic Versioning](https://semver.org).

## 0.2.0 - 2026-11-12

- Installable package with one command: `opcua-test run | report | sim` (was: loose scripts).
- Exit code follows the verdict: 0 PASS, 1 FAIL, 2 NO DATA.
- Samples carry the time they were really taken; all variables of a sample are read in one request.
- A variable name that is not in `target.variables` is refused instead of being reported as NO DATA.
- A test case without limits is refused even when the run has no matching samples.
- README: limits (polling rate, security), offline install. Example test cases moved to `examples/`.
- Releases carry a wheel and offline bundles for Linux and Windows. Python 3.11 or newer.

