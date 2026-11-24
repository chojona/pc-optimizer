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
- Plain-English diagnostic views for hardware, driver checks, stability, action history and saved network results. **Show technical details** displays the original data. Common field names, units and errors are explained locally; values, warnings and verification limits are retained.
- Wi-Fi & Network Center with automatic adapter detection, native WLAN telemetry, channel surveys, timestamped gateway/multiple-external latency, explicitly defined jitter, ICMP nonresponses and interface throughput charts.
- Consent-gated download/upload, configured DNS and loaded-latency benchmarks, persistent configuration snapshots, guarded comparisons and individually reversible power-management experiments.

## Wi-Fi & Network Center

Open **Wi-Fi & Network** in the sidebar. The inspected adapter selector shows model, driver, link rate, SSID, signal quality, band, center frequency, channel, power capabilities and read-only advanced properties. Live probes follow the actual OS IPv4 route to `1.1.1.1`, independently of the inspected adapter. Route/radio path changes reset time-based rolling probe windows and charts. **Diagnostics / advice** shows per-target P50/P95/P99/maximum, consecutive RTT variation, aligned multi-target spike evidence, signal correlation, alternative explanations and limited confidence. Window/minimum samples/targets are configurable; diagnostic events persist in SQLite. ICMP nonresponses never confirm application packet loss. See [the methods and architecture guide](docs/learning/network-diagnostics.md). Interface traffic comes from real byte counters; negotiated link speed is shown separately.

Nearby channel analysis uses Native WLAN BSS observations, deduplicated by BSSID across radios. Observations include their UTC timestamp. The optional **Review Wi-Fi radio survey** requests a scan only after approval and reports completion, failure or timeout. Scans can briefly increase latency. Co-channel AP counts and estimated adjacent 2.4 GHz overlap do not measure channel airtime, bonded-channel widths or non-Wi-Fi interference. A quiet-looking channel is not proof that moving to it will improve performance.

**Benchmarks** first asks for comparison conditions and explicit traffic consent. The fixed protocol uses 20 gateway/external ICMP rounds, five DNS lookups through the configured OS resolver, and three bounded HTTPS transfers per direction to Cloudflare. The maximum payload is 48 MiB downloaded and 12 MiB of synthetic zeros uploaded, plus protocol overhead. Requests have timeouts, byte limits and cancellation; no personal files are sent and redirects are rejected. These tests generate congestion and should run outside critical trading or gaming sessions, with the same location, power source, VPN, router and background workload. The user can cancel; partial results remain in history.

Throughput includes connection/TLS/server overhead and is a single-stream observation, not a certified maximum line rate. DNS timings can include cache hits and do not rank uncached resolvers. Loaded latency compares external ICMP during transfers against the preceding baseline. Short transfers or insufficient replies are **inconclusive**. Bottleneck saturation is unverified, so results have no bufferbloat grade. ICMP filtering or rate limiting may appear as loss. IPv6-only route probing and per-process byte accounting are explicitly **unsupported** in this backend; process disk I/O and socket counts are never presented as bandwidth. Native WLAN/location permissions and driver capabilities can make individual fields unavailable.

**History / comparison** offers an explicit observational Wi-Fi-versus-Ethernet mode for separate runs after a manual connection switch. Adapter, driver and route changes remain confounds; no connection is switched automatically. It also retains full before/after configurations and raw results in the existing SQLite database. Comparisons require distinct complete runs, stable route identity, matching adapter/driver/DNS/radio identity and test parameters, the same declared conditions, Wi-Fi signal within ten percentage points and comparable observed idle traffic. Differences are labeled observed improvement, regression, within variation or uncertainty unavailable. An uncontrolled internet test pair never establishes a verified causal improvement.

Recommendation cards explain evidence, risk, expected benefit and verification limits. The only writable network properties are driver-exposed `SelectiveSuspend` and `DeviceSleepOnDisconnect`, each reviewed and approved separately. These are optional power-transition experiments, with theoretical benefits and increased power consumption; they are not blanket gaming recommendations. The engine requires explicit approval and administrator rights, saves the original value before mutation, uses `-NoRestart`, verifies configured state and retains rollback on failure. Restore validates adapter identity and refuses to overwrite later changes. Effective driver behavior may need a later manual restart. There is no automatic adapter restart, connection switch, driver installation, security change, registry tweak or TCP tuning.

**Official drivers** performs a read-only Windows Update Agent driver search and matches offers to the routed device's PnP hardware/compatible IDs. It saves the source, installed version and candidate metadata. No candidates does not establish the latest OEM release; check the exact system/device, OS and release notes through its manufacturer. Official support links identify their manufacturer explicitly.

Implementation references: [Microsoft Native WLAN](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlangetnetworkbsslist), [scan behavior](https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlanscan), [power-management API](https://learn.microsoft.com/en-us/powershell/module/netadapter/set-netadapterpowermanagement), [Windows Update driver metadata](https://learn.microsoft.com/en-us/windows/win32/wua_sdk/idriverupdate), and [Cloudflare's documented benchmark endpoints](https://github.com/cloudflare/speedtest).

## Availability and interpretation

CPU temperature needs a compatible sensor provider. NVIDIA telemetry uses `nvidia-smi`; unsupported metrics remain unavailable. Storage benchmarks include operating-system caching and do not represent raw device throughput.

Driver releases are not automatically declared current: match the device and operating system against the official source. Driver installation uses the vendor installer or Windows Update. Firmware is reviewed through exact-model official instructions and is never flashed automatically.

GPU scoring requires an external benchmark. Gaming measurements require a supported PresentMon CSV. Compilation requires a compiler on PATH. Boot and shutdown timing depend on readable Windows diagnostic events.

Stability outcomes and performance changes are distinct. A completed driver installation does not establish a crash fix. Restart, shutdown, sleep and hibernation tests require explicit initiation in the GUI and save their state first. Save other open work before initiating them.

This repository includes a user-provided summary of prior diagnostic findings in `optimizer/stability.py`. It is labeled as imported evidence rather than newly verified analysis.

## Local data

Settings, action history, rollback state and benchmark results are stored in `data/optimizer.sqlite3`. Network snapshots include local adapter identities, SSID/BSSID and DNS configuration. The `data/` directory, virtual environment, logs, dumps and environment files are excluded from Git. Live ICMP probes use the IPv4 gateway and configurable external IPv4 targets (default `1.1.1.1`, `8.8.8.8`, `9.9.9.9`). Bulk benchmark traffic, DNS benchmark lookups, Wi-Fi scans and Windows Update checks are initiated manually; bulk benchmarks require traffic consent.

## Tests

```powershell
New-Item -ItemType Directory -Path data -Force | Out-Null
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp data/test-temp
```

Tests cover persistence, rollback guards, protected components, bounded benchmark files, result comparison, capture validation, imported evidence and saving state before desktop transitions. Network tests add native structure/channel decoding, provider failures, explicit approval, durable rollback and failed-action recovery, route handovers, benchmark cancellation/partial results, response limits, comparison confounds, official driver matching and GUI/history isolation. System-changing commands and external bulk traffic are mocked in automated tests.

## CI and releases

GitHub Actions tests pull requests and `main` on Windows with Python 3.12–3.14, then builds a verified source bundle and SHA-256 checksum. Pushing a version tag such as `v1.0.1` publishes that bundle as a GitHub Release after the same checks pass. See [CI/CD and release instructions](docs/ci-cd.md).

## Layout

- `optimizer/ui.py`: native desktop interface and background jobs.
- `optimizer/readable.py` and `optimizer/readable_ui.py`: plain-language diagnostic formatting and the original-data toggle.
- `optimizer/windows.py`: Windows commands, inventory and official sources.
- `optimizer/telemetry.py`: live sampling and network probes.
- `optimizer/network.py`: network discovery, monitoring, benchmarks, comparison and guarded actions.
- `optimizer/wlan.py`: read-only Native WLAN telemetry and approved radio surveys.
- `optimizer/network_ui.py`: the network dashboard using the existing worker pool and UI components.
- `optimizer/actions.py`: execution, protection checks and rollback.
- `optimizer/benchmarks.py`: benchmark engine and comparisons.
- `optimizer/stability.py`: imported evidence and transition tests.
- `optimizer/store.py`: SQLite persistence.
- `tests/`: core and GUI tests.
