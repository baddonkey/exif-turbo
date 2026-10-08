---
description: "Run the full test suite, wait until it has completely finished, and report the failed tests"
name: "Run tests"
agent: "agent"
---

Run the complete exif-turbo test suite and report the failed tests. Follow
these steps exactly. Do not change any code, do not try to fix failures, and do
not run pytest in any other way.

## Rules

- Use only the two commands below, in the terminal in **sync** mode, without a
  timeout. Run one command at a time, never in parallel.
- Never run a long blocking command (pytest, `--wait --max-wait <large>`): the
  terminal returns early from commands running longer than ~10 s and then
  stays busy. The wait command blocks for only 8 s, so it always completes.
- The commands `Set-Location` to the repo root first, because the terminal's
  working directory is not guaranteed.
- Decide what to do next **only from the last `RUN-STATUS:` line** in the
  output. Do not rely on the exit code; the terminal does not always report it.
- **Do not end your turn while the status is `STARTED` or `STILL_RUNNING`.**

## Steps

### 1. Start the run

```powershell
Set-Location "${workspaceFolder}"; & .\.venv\Scripts\python.exe scripts\run_tests_logged.py --detach
```

- `RUN-STATUS: STARTED`: the run is going in the background. Go to step 2.
- `RUN-STATUS: STILL_RUNNING`: a run is already in progress. Do not start
  another one; go to step 2 to follow it.
- If a low-disk-space `WARNING` is printed, mention it in the final report.

### 2. Wait for completion (repeat)

```powershell
Set-Location "${workspaceFolder}"; & .\.venv\Scripts\python.exe scripts\run_tests_logged.py --wait
```

Each call blocks for at most 32 seconds. A full run takes several minutes, so
expect to repeat this command many times (dozens); that is normal.

| Last line | Action |
|-----------|--------|
| `RUN-STATUS: STILL_RUNNING` | Run the same command again right away. Do not comment on progress between calls. |
| `RUN-STATUS: PASSED` | Go to step 3. |
| `RUN-STATUS: FAILED` | Go to step 3. |
| `RUN-STATUS: RUNNER_DEAD` | Go to step 3; report that the runner died and quote the last lines of the `pytest.log` it names. |
| `RUN-STATUS: NO_RUN` | Go back to step 1. |
| No `RUN-STATUS` line / garbled output (e.g. `CommandNotFoundException`) | Run the same wait command again. It is always safe to repeat. |

### 3. Report

Report what the final `--wait` output printed (also stored as `summary.txt` in
the run folder):

1. The **Result** and **Totals** lines.
2. **Failed tests**: every `FAILED` / `ERROR` entry with its node id and
   message, as a list.
3. **Crashed / timed-out groups**, if any, with their reason. For each one,
   search the run's `pytest.log` for the last test that started in that group
   (or a `Timeout` stack dump) and name it.
4. The path to the full log.

Keep the report short. Do not suggest fixes unless asked.
