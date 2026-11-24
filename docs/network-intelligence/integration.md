# Integrating Network Intelligence v1

The user approved the contract before implementation; it was published on
[issue #10](https://github.com/chojona/pc-optimizer/issues/10#issuecomment-7147014782).
The focused contract commit is `9c244a5ef8322410fe37d96ca671d65cf72f992b`.
Consumers #11 and #12 own UI/AI wiring and must not edit the backend contract.

## Existing data, new analysis

```python
from optimizer.network_intelligence import analyze, from_event

# event is the existing saved diagnostic event *payload*, not the database row.
# as_of is supplied by the caller as a UTC ISO 8601 string.
snapshot = from_event(event, as_of=as_of)
result = analyze(snapshot)
```

`from_event` accepts `captured_at`, `rounds`, `config`, `stable_round` from
`NetworkMonitor` diagnostic events. It ignores unrelated event metadata and
precomputed diagnosis; only validated raw measurements produce findings. The
adapter copies returned containers, accepts the existing live tuple of target
addresses, and rejects oversized histories. It does not fetch events or invoke
`network.py`; importing that module would bring in host-specific providers.
The data format is reused without changing existing diagnostics, monitor output,
recommendation cards, WLAN telemetry or SQLite persistence.

For live integration the UI worker can construct an event-shaped payload from
the monitor's config, route-stable round window and capture timestamp. Snapshot
construction must be synchronized with sampling/configuration changes; never
mix route identities or clocks. Do not silently truncate oversized histories.
The existing default 120-second window normally fits the 256-round cap, but
long configured windows may require an explicit shorter capture by the caller.

`as_of` is evaluation time for freshness. To replay historical evidence at its
capture time, deliberately set it to `captured_at` and label the display as
historical. For current advice, use current UTC; old evidence becomes stale.
Neither entrypoint reads the host clock. Malformed input raises `ValueError`;
the UI should show a caller-data error, never an empty healthy state.

## Presentation and AI

Render `summary.text`, findings with confidence and evidence, recommendations
and limitations together. `summary.state=ok` only indicates sufficient aligned
observations for the reported pattern; it is not a network health certificate.
Findings can coexist: an ICMP observation may be valid while there is still
insufficient evidence for path isolation. Confidence is a rule label, not a
probability. Stable IDs are suitable for rendering/deduplication. Evidence
references are JSON Pointers into the returned result, not indexes into a
changing live history. No localized/user-provided text becomes a command.

Run inference in the consumer's existing background worker, keeping request IDs
so late results cannot replace a newer capture. This synchronous bounded API
does not manage Qt lifetime, signals, cancellation or AI runtimes. It has no
I/O, shared caches, mutable global state or internal threads. Cancellation
between calls belongs to the consumer. Do not schedule unlimited concurrent
analyses; at most one outstanding request per panel is a suitable UI policy.

Input and output may contain raw external addresses/provider error messages;
this package is not a privacy redactor. AI must validate/redact evidence under
its own contract before prompting. No provider error is executed. Findings
and recommendations remain advisory; `requires_approval` is always true, even
when a recommendation only asks for more observations. The engine never
calls the existing host-action executor.

## Algorithm and costs

Validation bounds JSON traversal to 16384 nodes, depth 8, 1024-character strings,
512 KiB serialized UTF-8 and 256 chronological rounds. Bounds are cumulative;
a fully populated six-target history can hit the node cap before the round cap.
JSON encoding stops at the byte cap; expensive statistical work starts only
after validation. Config objects and probe fields use exact keys/types to make
bad units, booleans-as-numbers and contradictory error/success values visible.

The existing `diagnostics.analyze` computes RTT statistics, missing-response
percentages, consecutive-success jitter, rolling median/MAD spike flags,
aligned multi-target coincidences and signal/RTT Pearson correlation. The new
entrypoint excludes stale rounds first and skips path inference entirely on
unstable identity. It translates the unchanged statistical result into stable
findings with evidence references and a manual next step.

For n rounds and t targets, repeated sorting for rolling medians/MAD dominates:
O(t n² log n) worst-case time and O(t n) memory. Validation/serialization adds
O(B) time and memory for bounded input bytes B. t<=6, n<=256; no measured speed
improvement or latency guarantee is claimed. Simultaneous callers multiply
costs; this API does not impose a process-wide scheduler.

## Limits and manual validation

ICMP nonresponse is not application packet loss. Configured target routes can
differ under VPN/policy routing. Gateway/external spike coincidence does not
prove a local fault; stable gateway ICMP does not exclude forwarding trouble.
Correlated targets need not be independent. Signal percent is not dBm, and a
correlation (including a weak one) is not a causal radio diagnosis. No channel
airtime, per-process bandwidth, IPv6-only path, application loss or throughput
saturation is measured here. Unknown/missing signal values stay unavailable.

No live probes or system changes are required to validate this package:

1. Load `examples.json` with the standard library, analyze each `snapshot`, and
   compare its expected state/finding; synthetic inputs contain no user data.
2. In a later opt-in manual app session, use an already captured event from one
   stable route and an explicit evaluation time. Compare the result's diagnostic
   field with the existing diagnostic view for the same retained rounds.
3. Advance evaluation past the window: the old finding must disappear and stale
   evidence must be reported. Set stable_path false: path inference must stop.
4. Review application telemetry separately when an ICMP nonresponse is shown.
   Initiating live captures/traffic or changing settings requires the existing
   explicit user controls; this document authorizes neither.

Automated synthetic tests cannot validate an actual ISP/router/radio fault or
Windows driver behavior. UI scaling/cancellation/rendering belongs to #11 and
local runtime/privacy behavior belongs to #12. Windows CI remains a separate
required publication check; local Windows/Python 3.14 checks do not substitute
for its Python 3.12/3.13 matrix or source-bundle job.
