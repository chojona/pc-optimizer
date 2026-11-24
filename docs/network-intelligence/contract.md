# Network Intelligence v1 contract (proposed)

Owner: issue #10, `codex-20261124-network-01`. Consumers: #11 (UI), #12 (AI).
This proposal must be agreed before engine implementation or consumer integration.

## Public API

`optimizer.network_intelligence.analyze(snapshot: dict) -> dict` is synchronous,
deterministic, standard-library-only pure analysis. It does not read the clock,
probe, import Qt/model runtimes, write storage, or execute recommendations.
The caller runs it in its worker and supplies an explicit evaluation time.
Malformed caller input raises `ValueError`; valid missing evidence returns
`summary.state = "insufficient"`. No other operational failures are expected.

## Input envelope

All objects use the exact documented keys; unknown keys and unsupported versions
are rejected rather than silently interpreted. Required top-level keys:

- `schema_version`: integer `1` (booleans are not integers in this contract).
- `captured_at`: UTC ISO 8601 timestamp of snapshot capture.
- `as_of`: UTC ISO 8601 evaluation timestamp, at or after `captured_at`.
- `stable_path`: boolean; false means route identity changed during capture.
- `config`: existing `DiagnosticConfig.payload()` fields, listed below.
- `rounds`: chronologically ordered list of existing diagnostic rounds, listed below.

Timestamps must have `Z` or `+00:00` UTC offsets. Every round's `captured_at`
must be at or before snapshot `captured_at`. Age is evaluated against `as_of`,
never the host clock. Evidence older than `config.window_seconds` is excluded;
excluded data is explained. A changed route suppresses causal path inference.
Callers must only combine rounds from a single route identity and monotonic
clock session; route/BSSID/channel changes start a new window as in NetworkMonitor.

`config` contains all existing fields: `window_seconds` (integer 10–3600),
`min_samples` (integer 3–1000), `external_targets` (2–5 distinct IPv4 address
strings), `alignment_seconds` (number >0 and <=1), `spike_floor_ms` (number >0),
`min_spikes` (integer 1–1000). Version 1 accepts at most **256 rounds**, at most
**512 KiB** of compact UTF-8 JSON, nesting depth 8, and strings at most 1024
characters. These bounds apply before calling the legacy statistical analyzer.
Numbers must be finite; RTT is between 0 and 60000 ms. No custom Python objects,
cycles, tuples, NaN, infinity, or non-string object keys are accepted.

Each round has required `captured_at`, `at`, `probes` and optional
`signal_percent`, `signal_at`. `at`, probe `start`/`end`, and `signal_at` are
nonnegative monotonic **seconds from the same clock**, not UTC or durations.
Round `at` values are strictly increasing. A probe start must be >= round `at`;
end must be >= start. Round UTC and monotonic offsets must agree within two
seconds, allowing the existing whole-second capture timestamps. Signal freshness
is assessed using `signal_at` against gateway dispatch, as in diagnostics.

`probes` maps `gateway` and/or configured external IPv4 strings to objects with
required `start`, `end`, `ms`, `error`. Missing probe keys mean unavailable,
not attempted. `ms=null,error=null` means an ICMP attempt without a response;
`ms=null,error="provider message"` means provider failure, excluded from the
nonresponse denominator. Errors must be nonempty strings or null; an error and
a numeric RTT together are invalid. `signal_percent` is null or 0–100 signal
quality percent, **not dBm**; a nonnull signal requires `signal_at`. Missing or
null values never become zero. Provider messages are untrusted display data.

## Output

JSON object with `schema_version=1`, `summary`, `findings`, `recommendations`,
`limitations`, and `evidence`. Output contains no timestamps generated internally.

- `summary`: `{state: "ok"|"insufficient", text: string}`. `ok` means sufficient
  evidence for the reported pattern, never a healthy-path or causal guarantee.
- Each finding: `{id, severity, evidence_refs, confidence, explanation}`.
  Severity is `info` or `warning`; confidence is `insufficient`, `low`, or
  `moderate`, explicitly heuristic and never a measured probability.
- Each recommendation: `{id, rationale, evidence_refs, risk, requires_approval}`.
  Risk is `low` or `moderate`; `requires_approval` is always true. Suggestions
  describe manual observation/comparison steps, with no executable commands.
- `limitations`: list of strings, including ICMP vs application-loss semantics,
  route/policy uncertainty, unmeasured airtime and heuristic confidence.
- `evidence`: `{diagnostic, input_rounds, analyzed_rounds, stale_rounds}`.
  `diagnostic` is existing `diagnostics.analyze` output over retained rounds,
  or null when route identity is unstable. References are JSON Pointers into
  the returned object (for example `/evidence/diagnostic/shared_spikes`).

Finding IDs use `network.<legacy fault>` plus independent `network.stale_data`,
`network.unstable_path`, `network.provider_errors`, `network.missing_probes`,
`network.wifi_signal_correlation`, and `network.wifi_signal_unavailable` when
applicable. Recommendation IDs use `network.collect_evidence`,
`network.compare_application`, `network.compare_local_path`, or
`network.compare_external_path`. IDs and ordering are deterministic and are
identities of rules, not individual events. Consumers display explanations,
confidence and limitations together and tolerate additional future finding IDs.

## Compatibility and integration

Existing `diagnostics.analyze`, `network.recommendations`, monitor results and
stored events retain their public behavior. A pure `from_event(event, *, as_of)`
adapter will project existing diagnostic event fields into this envelope,
validating it without probing. It will reject oversized histories rather than
silently selecting a biased subset. UI owns scheduling, freshness updates and
all wiring. AI consumes this result read-only and must not infer missing data.
Do not reinterpret `loss_percent` (a legacy alias for ICMP nonresponse) as
application packet loss. Unsupported IPv6-only paths, process bandwidth,
channel airtime, throughput saturation and application loss remain limitations.

## Synthetic example

```json
{"schema_version":1,"captured_at":"2026-11-24T23:00:00Z","as_of":"2026-11-24T23:00:00Z","stable_path":true,"config":{"window_seconds":120,"min_samples":20,"external_targets":["1.1.1.1","8.8.8.8","9.9.9.9"],"alignment_seconds":0.15,"spike_floor_ms":10.0,"min_spikes":3},"rounds":[{"captured_at":"2026-11-24T23:00:00Z","at":100.0,"signal_percent":null,"signal_at":100.0,"probes":{"gateway":{"start":100.0,"end":100.1,"ms":null,"error":"synthetic provider unavailable"},"1.1.1.1":{"start":100.01,"end":100.1,"ms":12.0,"error":null}}}]}
```

This valid sparse/provider-error example yields an insufficient summary. An
empty `rounds` list is also valid and insufficient. A numeric version other than
1, a negative RTT, a local timestamp, or a nonfinite number raises `ValueError`.
Deterministic synthetic fixtures will cover stable, shared, external-only,
conflicting, stale, missing, nonresponse, provider-error and unaligned evidence.

## Cost and validation

For n<=256 rounds and t<=6 targets, the reused repeated median/MAD spike
algorithm costs O(t n² log n) time and O(t n) memory in the worst case; this is
an analytical bound, not a measured speed claim. Validation is bounded by JSON
size, depth and node limits (16384 nodes). No installation is needed.
Tests will cover strict validation, determinism, serialization, evidence-pointer
resolution, alignment, stale filtering and absence of I/O. Existing regression
tests, the full suite and Windows CI remain required before review.
