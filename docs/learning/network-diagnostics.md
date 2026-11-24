# Evidence-based network diagnostics

## Purpose and networking fundamentals

The Network Center observes a path and proposes follow-up experiments. It never changes system settings automatically. Existing approval and rollback guards remain intact. Driver searches remain available on demand; a newer driver alone is not evidence of a relevant fix, so routine driver-update recommendations have been removed.

The default IPv4 gateway is the first router on the selected route. An external round-trip time (RTT) includes outbound and return transit, endpoint response handling and local scheduling. Gateway RTT is not a component that can simply be subtracted from external RTT: replies can follow different paths and routers may prioritize forwarding over responding to ICMP.

The live targets default to 1.1.1.1, 8.8.8.8 and 9.9.9.9. Several targets reduce dependence on one responder but are not independent experiments; paths can share routers and congestion. Windows routing follows 1.1.1.1 for path identity. Split tunnels, VPNs and policy routing can send other targets elsewhere. IPv6-only routes and per-target route tracing are unsupported. Probes are not bound to the inspected adapter.

**An ICMP nonresponse is not confirmed application-level packet loss.** A missing reply can reflect an echo request or reply dropped in transit, a timeout, filtering or responder rate limiting. The native probe also returns `None` for some native API failures; these cannot be distinguished from nonresponses by this backend. Python provider exceptions are recorded separately and excluded from the ICMP attempt denominator. Application packet loss is always unavailable, never derived from ping. DNS/HTTPS failures are transaction failures and do not establish packet-loss counts. Correlate symptoms with actual game, call or service telemetry before attributing application failure to the network.

## Sampling, timestamps and rolling windows

`NetworkMonitor` reuses the existing native ICMP implementation and GUI worker pool. Every polling cycle submits gateway and external probes to a bounded thread pool. Each result records monotonic start/end times, RTT or nonresponse, and a provider error when raised. The round also records UTC capture time, monotonic round time and signal query time. UTC provides human-readable history; monotonic time controls expiration and alignment without sensitivity to wall-clock adjustments. Monotonic values are meaningful only within the originating process.

A round qualifies for cross-target spike analysis when successful gateway and external probe starts differ by at most 150 ms. At least two external targets must qualify in the same round. This is a dispatch-alignment tolerance, not a claim of simultaneous packet arrival. Completion time is deliberately not used for pairing: a slow reply must not migrate to a later round. End timestamps permit audit of long-running probes. A slow GUI tick skips overlapping rounds rather than fabricating samples.

Defaults: 120-second rolling window, 20 successful baseline replies per target and 20 aligned evaluable rounds, three repeated spikes, and three external targets. Window (10–3600 seconds), minimum samples (3–1000) and 2–5 distinct external IPv4 addresses are configurable and saved in SQLite. Alignment and spike thresholds are configurable through the immutable configuration object. Expiration uses sample age, with a defensive 10,000-round memory cap. These are configurable heuristics, not universal service-quality thresholds.

Path identity includes interface index/GUID, gateway and observed Wi-Fi BSSID/channel. A change resets evidence, as does changing measurement configuration. A route change during a round discards the round from analysis and clears evidence. A route that changes and returns entirely between the two checks cannot be detected. Initial/reset charts contain no invented history. Very short windows or large minimum requirements may never warm up: analysis stays insufficient rather than relaxing requirements. At the default two-second polling interval, baseline plus evaluation requires roughly 80 seconds; provider delays can extend this.

## Statistical methods

All latency statistics describe **successful replies in the current window**, so filtering/timeouts can bias them. The table still displays successes and total attempts, and unanswered percentage, to expose that selection.

- P50, P95 and P99 use the empirical nearest-rank definition: sort `n` successful RTTs and select the 1-based position `ceil(p*n)`. P50 is the lower central observation for an even sample count, rather than an interpolated median. The spike baseline separately uses Python's median, averaging the two central observations when needed.
- Maximum is the largest observed successful RTT. It is not a bound on future latency.
- Mean latency is retained for existing dashboard cards. Benchmarks retain median summaries for comparisons.
- Jitter means **mean absolute difference between consecutive successful RTT measurements**: `mean(abs(RTT[i] - RTT[i-1]))`. A missing reply, missing target or provider error breaks a pair. Jitter P95 is the nearest-rank P95 of those absolute differences. Pair counts accompany statistics. There is no gap bridging and no conversion of timeouts to zero RTT.
- This jitter is round-trip variation, not RFC 3393 one-way IP delay variation, RTP jitter or a standard deviation. Different definitions are not interchangeable.
- Percentiles remain visible with few replies but are descriptive only. P99 below 100 successful replies is explicitly flagged as unstable; even larger samples do not establish a reliable population tail estimate. No confidence interval or significance claim is invented.
- Minimum sample counts gate fault analysis and mark target statistics as sufficient/insufficient. Nonresponse evidence requires the minimum number of attempts; it can be reported with low confidence even when too few replies exist for latency analysis.

Percentile conventions vary; the chosen convention matches the existing benchmark helper. See [NIST percentile definitions](https://www.itl.nist.gov/div898/handbook/prc/section2/prc262.htm). For distinctions among delay-variation metrics, see [RFC 3393](https://www.rfc-editor.org/rfc/rfc3393.html) and [RFC 5481](https://www.rfc-editor.org/rfc/rfc5481.html).

## Spike detection and fault isolation

For each target, scan the current window in time order. Once at least the configured minimum prior successful replies exists, calculate their median `m` and median absolute deviation `MAD`. A successful RTT is a spike if it exceeds:

```
m + max(10 ms, 3 * 1.4826 * MAD, 0.5 * m)
```

The baseline uses prior replies only; the candidate cannot raise its own threshold. Baselines adapt as the rolling window advances. Sustained latency increases eventually become the baseline, so this detector finds excursions rather than proving all persistent latency problems. The 1.4826 scale relates MAD to standard deviation under a normal model, but network RTT is often skewed and autocorrelated; the rule does not assert a normal model or a statistical false-positive probability.

Per-target evidence retains aligned-pair counts, shared spikes and external-only spikes. The engine also counts same-round agreement across at least two external targets:

| Pattern with enough evaluable rounds | Interpretation and experiment |
| --- | --- |
| Repeated gateway and multiple-external spikes | Shared path suspected; inspect local traffic/router load and compare a manual Ethernet trial |
| Multiple-external spikes with stable gateway | Beyond-gateway path suspected; repeat at idle and collect timestamped application/ISP evidence |
| Both shared and external-only patterns | Conflicting evidence; retain low confidence and isolate workload/medium in repeated trials |
| Gateway spikes while external targets stay stable | Gateway ICMP handling may differ from forwarding; validate the application first |
| One external target repeatedly spikes | Target-specific evidence; try another endpoint and the actual application path |
| Repeated ICMP nonresponses | Check another protocol/application; no confirmed application packet loss |
| No repeated pattern | No repeated spikes detected in this window, not proof of a healthy application path |
| Too few aligned successful rounds | Insufficient evidence |

Confidence labels are heuristic: insufficient, low or moderate; never a calibrated probability or a confirmed root cause. Stable gateway responses cannot rule out a local forwarding problem. Every finding retains alternatives including ICMP prioritization/filtering, host scheduling, background load and shared external infrastructure. Recommendations are tied to counts and the observed pattern, and propose measurements/manual experiments rather than automatic tuning.

## Signal correlation and medium comparisons

Signal correlation pairs the routed Wi-Fi interface's signal quality percentage with gateway RTT when the signal query and probe start are within two seconds. Pearson's `r` is covariance divided by the product of centered vector lengths. It requires the configured minimum paired observations and nonzero variation in both series. Constant, stale, absent or insufficient data returns unavailable. Cached BSS RSSI is deliberately excluded. Signal quality percentage is not calibrated dBm; WLAN provider caching, range restriction, autocorrelation, movement and concurrent traffic can distort correlation. A negative coefficient can be consistent with weaker radio conditions accompanying higher RTT, but proves no cause.

History comparison has an explicit Wi-Fi-versus-Ethernet mode. The user manually switches connections and runs the existing approved benchmark protocol; the application never switches adapters. This mode permits the expected differences in adapter/driver/radio/route identity while requiring complete, stable individual runs, known adapter/driver identity, matching protocol and declared environment, matching DNS, comparable idle traffic and stable Wi-Fi signal. Normal before/after mode still requires matching full context. Medium comparison explicitly names adapter, driver and route changes as confounds. Alternate Wi-Fi/Ethernet trials under matched location, power source, router, VPN and workload; a single uncontrolled pair cannot establish causality.

## Architecture and persistence

- `optimizer/diagnostics.py`: immutable validated configuration, pure nearest-rank/jitter statistics, robust spike flags, aligned multi-target evidence, signal correlation, conservative fault classification and measured follow-up advice. Pure functions enable deterministic offline tests.
- `optimizer/network.py`: discovery and route checks, timed concurrent probes, rolling history, configuration reset, event persistence, existing benchmarks and comparison mode. No independent probe service or new dependency was added.
- `optimizer/telemetry.py`: reused Windows ICMP API probe; the rest of the application keeps its existing telemetry behavior. The Network Center uses the new explicitly defined statistics rather than altering unrelated telemetry.
- `optimizer/wlan.py`: reused native read-only connection quality and BSS inventory. No radio scan is initiated by the diagnostic engine.
- `optimizer/store.py`: existing SQLite connection/lock infrastructure plus additive `network_events` table. Evidence events contain capture time, path, configuration, full diagnosis and raw rolling rounds. Transitions are saved immediately; recurring evidence is saved at most once per minute. Events survive restart and are separate from benchmark history so monitoring does not crowd out benchmark selections. Latest 200 events are queried for the UI; records are not automatically deleted. Long-running installations can grow the database. Raw rounds may include local addressing and interface identities; storage stays local in the existing ignored `data/` directory.
- `optimizer/network_ui.py`: existing background jobs, six tabs and chart widgets; per-target statistics, configuration controls, evidence and limitations, diagnostic event inspection and explicit medium-comparison mode. Scoped dark styling avoids modifying global UI styles shared with the AI Optimizer. Compact charts and metric text leave more room for diagnostic tables; tab scroll buttons preserve readability in narrow windows.
- `tests/test_diagnostics.py`: synthetic shared/external-only/target-specific spikes, conflicting evidence, dispatch skew, ICMP nonresponses, provider errors, insufficient data, exact percentile/jitter expectations, stale/constant signal, window expiration, route handover, SQLite reopen, configuration validation and cross-medium comparison. Existing network tests continue to cover approval guards, cancellation, bounded transfers and rollback.

This work is isolated on `codex/evidence-network-diagnostics`, based on the existing Network Center branch, in `data/network-diagnostics`. Shared optimizer/UI infrastructure is reused without editing AI Optimizer implementation files. Automated validation is offline: native calls, system changes and external transfers are mocked. Hardware/ISP behavior and real Wi-Fi-versus-Ethernet performance require actual user-controlled trials and are not claimed by synthetic validation.
