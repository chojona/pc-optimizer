# PC Optimizer

A local Windows desktop application built with Python, PySide6 and psutil. It combines live monitoring, explicit optimization actions, repeatable benchmarks and stability observations in a dark native GUI.

## Run on Windows

Requires Windows 10 or 11 and Python 3.12 or later.

1. Clone this repository.
2. Run `setup.ps1` in PowerShell to create `.venv` and install the pinned dependencies.
3. Double-click `Launch-PC-Optimizer.cmd`.

Alternatively, after setup:

```powershell
.\.venv\Scripts\python.exe main.py
```

Use **Activity & Settings → Restart as administrator** for actions requiring Windows UAC elevation. No optimization is applied automatically at launch.

## Features

- Asynchronous CPU, NVIDIA GPU, memory, network, disk and hardware monitoring.
- Power-plan and pagefile policy actions with persistent rollback state and verification.
- Windows storage maintenance and integrity diagnostics.
- Startup inventory, supported current-user entry disable/restore, and explicit process termination with protected-component checks.
- CPU, memory, bounded file I/O, network, idle-load, boot-event and C++ compilation benchmarks.
- Local benchmark history, before/after comparisons, and PresentMon CSV import.
- Imported prior diagnostic findings, event-log inspection, paging/disk-latency observations and user-initiated desktop transition tests.
- Installed driver inventory, Windows Update metadata checks and official manufacturer links.

## Availability and interpretation

CPU temperature needs a compatible sensor provider. NVIDIA telemetry uses `nvidia-smi`; unsupported metrics remain unavailable. Storage benchmarks include operating-system caching and do not represent raw device throughput.

Driver releases are not automatically declared current: match the device and operating system against the official source. Driver installation uses the vendor installer or Windows Update. Firmware is reviewed through exact-model official instructions and is never flashed automatically.

GPU scoring requires an external benchmark. Gaming measurements require a supported PresentMon CSV. Compilation requires a compiler on PATH. Boot and shutdown timing depend on readable Windows diagnostic events.

Stability outcomes and performance changes are distinct. A completed driver installation does not establish a crash fix. Restart, shutdown, sleep and hibernation tests require explicit initiation in the GUI and save their state first. Save other open work before initiating them.

This repository includes a user-provided summary of prior diagnostic findings in `optimizer/stability.py`. It is labeled as imported evidence rather than newly verified analysis.

## Local data

Settings, action history, rollback state and benchmark results are stored in `data/optimizer.sqlite3`. The `data/` directory, virtual environment, logs, dumps and environment files are excluded from Git. The application does not upload telemetry; live ICMP probes use `1.1.1.1`, and Windows Update checks are initiated manually.

## Tests

```powershell
New-Item -ItemType Directory -Path data -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp data/test-temp
```

Tests cover persistence, rollback guards, protected components, bounded benchmark files, result comparison, capture validation, imported evidence and saving state before desktop transitions. System-changing commands are mocked in automated tests.

## Layout

- `optimizer/ui.py`: native desktop interface and background jobs.
- `optimizer/windows.py`: Windows commands, inventory and official sources.
- `optimizer/telemetry.py`: live sampling and network probes.
- `optimizer/actions.py`: execution, protection checks and rollback.
- `optimizer/benchmarks.py`: benchmark engine and comparisons.
- `optimizer/stability.py`: imported evidence and transition tests.
- `optimizer/store.py`: SQLite persistence.
- `tests/`: core and GUI tests.
