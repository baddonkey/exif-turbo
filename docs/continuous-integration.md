# Pull Request Quality Checks

The `Quality` workflow runs on pull requests, pushes to `main`, and manual
dispatch. It uses read-only repository permissions and cancels superseded runs
on the same PR. Tests run against Windows 2025 and Ubuntu 24.04 with Python
3.11 and 3.13, plus macOS 15 ARM64 with Python 3.13. These jobs validate tested
combinations; they are not certification of every Python version or distribution.

## Required Check

Configure branch protection or a repository ruleset to require **Required
Quality** before merging. That stable check succeeds only when every test-matrix
job and **Static Quality** succeed; failed, canceled, or skipped prerequisite
jobs fail the aggregate. Adding the workflow does not itself configure branch
protection. Ruleset changes require repository-administrator approval.

## Test Execution

CI synchronizes the committed dependency lock with uv 0.13.0 into the repository
`.venv`, using the `dev` extra. Linux installs Qt runtime libraries and uses Xvfb;
the other systems use their native desktop sessions. ExifTool is installed and
verified on every platform, preventing its missing-tool modal from intercepting
UI test input. The repository selects Qt rendering per platform; CI does not
force Qt's software scene graph on Linux or macOS. CI runs focused AI safety
checks followed by the complete `scripts/run_tests_logged.py` runner in the
foreground. The runner isolates each UI test file, writes subprocess output to
files rather than pipes, and enforces 120-second per-test and 900-second per-group
timeouts. Jobs have a separate 35-minute wall-clock limit. Native crashes fail
CI without automatic retries.

`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `EXIF_TURBO_TEST_OFFLINE` are enabled
in test jobs. The last activates an autouse pytest fixture that rejects Python
socket connections before network access. AI tests must still mock model loading,
including cached weights: offline mode is not a substitute for mocks. This guard
does not sandbox subprocesses or native libraries; tests must not launch network
clients or native downloads. Dependencies are installed before test execution
and may use the network.

All run folders, summaries, JUnit reports, and crash/timeout logs are uploaded
even when tests fail. Artifacts are retained for 14 days. Inspect the failing
job's artifact rather than treating a missing report as a passing test group.

## Static Baselines

The Windows/Python 3.13 static job checks all Python under `src/` and `scripts/`
and all application QML. Python syntax errors and fatal QML parse diagnostics
always fail, including during baseline updates. Pyright 1.1.414 runs in basic
mode with Python 3.11 syntax/type compatibility and the active interpreter's
locked dependency stubs. Qt's installed `qmllint` uses structured JSON output.

Existing diagnostics are explicitly recorded in `.github/quality/baseline.json`.
The gate compares counts by tool, file, rule, severity, and message, not line
numbers. New messages and increases in identical diagnostics fail; fixes pass.
Replacing an old error with a different one still fails. Removing and introducing
an identical message within the same file may offset counts; this is a debt
baseline, not proof of strict type safety or runtime correctness. Existing Qt
context-property warnings remain covered by runtime UI tests.

Run locally using the same locked dependencies as CI:

```powershell
uv sync --locked --no-default-groups --extra dev --python 3.13 --no-managed-python
.\.venv\Scripts\python.exe scripts/check_quality.py
```

Do not silently update the baseline to make a failing PR pass. When intentionally
changing checker versions or reviewed diagnostic debt, regenerate it with
`scripts/check_quality.py --update-baseline`, explain the changes in the PR, and
review the diff. The checker version is pinned; Qt and dependency versions come
from `uv.lock`. Raw JSON and a summary are uploaded as the `static-quality`
artifact and generated locally under the ignored `logs/quality/` directory.

## Performance

Large-memory AI benchmarks are intentionally excluded from shared-runner merge
gates. Run the reproducible commands in `docs/ai-performance.md` on an adequately
provisioned machine and attach measurements to performance-focused changes.