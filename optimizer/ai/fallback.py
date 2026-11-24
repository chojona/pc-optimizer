"""Deterministic, evidence-only suggestions.

This is what the engine returns whenever the local model is absent, slow, wrong
or refused, so diagnostics never depend on a model being installed. Every rule
is a pure function of the collected evidence mapping: same evidence, same
suggestions, same order. Nothing here proposes an executable command, and every
suggestion cites keys that exist in `evidence`.
"""
from .evidence import LABELS


def _cite(evidence, *keys):
    return [k for k in keys if k in evidence]


def suggest(evidence, limit=5):
    """Return up to `limit` deterministic suggestions for `evidence`.

    Ordered most-specific first: measured faults, then link conditions, then
    general hygiene, so truncation drops the least specific advice.
    """
    out = []

    def add(identifier, title, rationale, risk, *keys):
        cited = _cite(evidence, *keys)
        if not cited or any(s['id'] == identifier for s in out):
            return
        out.append(dict(id=identifier, title=title, rationale=rationale, evidence=cited,
                        risk=risk, requires_approval=True, source='deterministic'))

    fault = evidence.get('diagnostic.fault')
    confidence = evidence.get('diagnostic.confidence')
    if fault == 'shared_path_suspected':
        add('diagnostic-shared-path', 'Check local traffic and router load, then compare a wired trial',
            f"Gateway and external targets spiked together in {evidence.get('diagnostic.shared_spikes')} "
            f"aligned rounds (confidence {confidence}). That points at the local segment rather than "
            'the wider internet, but it does not prove it.',
            'low', 'diagnostic.shared_spikes', 'diagnostic.aligned_rounds', 'diagnostic.fault')
    elif fault == 'beyond_gateway_suspected':
        add('diagnostic-beyond-gateway', 'Keep timestamps for an ISP or application-path conversation',
            f"{evidence.get('diagnostic.external_only_spikes')} aligned rounds spiked on multiple external "
            f"targets while the gateway stayed stable (confidence {confidence}). Local changes are unlikely "
            'to help; evidence beyond the gateway is what moves this forward.',
            'low', 'diagnostic.external_only_spikes', 'diagnostic.aligned_rounds', 'diagnostic.fault')
    elif fault == 'gateway_icmp_only':
        add('diagnostic-gateway-icmp', 'Confirm the symptom with the application before changing anything',
            f"Only the gateway spiked, in {evidence.get('diagnostic.gateway_only_spikes')} aligned rounds. "
            'Routers often de-prioritise replies to probes while forwarding normally, so this may be a '
            'measurement artefact rather than a fault.',
            'low', 'diagnostic.gateway_only_spikes', 'diagnostic.fault')
    elif fault == 'insufficient_evidence':
        add('diagnostic-collect-more', 'Measure for longer before drawing a conclusion',
            f"Only {evidence.get('diagnostic.aligned_rounds')} aligned rounds were available. Any "
            'classification from this little data would be noise.',
            'low', 'diagnostic.aligned_rounds', 'diagnostic.fault')
    elif fault == 'conflicting_evidence':
        add('diagnostic-conflicting', 'Repeat the measurement at idle, then compare a wired trial',
            'Shared and external-only spikes both appeared, which no single cause explains well. '
            'Removing background load and the radio from the picture separates them.',
            'low', 'diagnostic.shared_spikes', 'diagnostic.external_only_spikes', 'diagnostic.fault')

    nonresponse = evidence.get('diagnostic.gateway_nonresponse_percent')
    if nonresponse is not None and nonresponse > 0:
        add('diagnostic-nonresponse', 'Check a second protocol before calling this packet loss',
            f"{nonresponse}% of gateway probes went unanswered. Devices are allowed to ignore or "
            'rate-limit probes, so this is not evidence of application packet loss on its own.',
            'low', 'diagnostic.gateway_nonresponse_percent')

    signal = evidence.get('network.signal_percent')
    if signal is not None and signal < 60:
        add('wifi-signal', 'Compare a wired trial from the same location',
            f"Reported Wi-Fi signal quality is {signal}%. A weak radio path costs retries and jitter; "
            'a wired comparison from the same spot separates the radio from everything else.',
            'low', 'network.signal_percent', 'network.rssi_dbm', 'network.link_kind')

    peers = evidence.get('network.cochannel_peers')
    if peers:
        add('wifi-channel', 'Survey the router channel from the router interface',
            f"{peers} other access points were cached on the same band and channel. Counts do not "
            'measure airtime, so this is a hint to survey, not proof of congestion.',
            'low', 'network.cochannel_peers', 'network.channel', 'network.band')

    if evidence.get('network.power_savings_enabled'):
        add('adapter-power-savings', 'Review adapter idle power saving only if resume faults are documented',
            'The adapter has idle power-saving properties enabled. Disabling them increases power use '
            'and helps only with documented idle or resume faults; no such fault is established here.',
            'moderate', 'network.power_savings_enabled', 'network.link_kind')

    for direction in ('download', 'upload'):
        key = f'benchmark.{direction}_loaded_increase_ms'
        increase = evidence.get(key)
        if increase is not None and increase > 15:
            add(f'queueing-{direction}', f'Investigate queueing during {direction}',
                f"Response time rose by {increase} ms while the {direction} ran. Saturation was not "
                'verified, so treat this as a queueing hint rather than a measured bufferbloat grade.',
                'low', key, f'benchmark.{direction}_mbps')

    failures = evidence.get('benchmark.dns_failure_percent')
    if failures:
        add('dns-failures', 'Re-test name lookups against a second resolver',
            f"{failures}% of name lookups failed with the configured resolver. Comparing another "
            'resolver separates a resolver problem from a path problem.',
            'low', 'benchmark.dns_failure_percent', 'benchmark.dns_ms')

    health = evidence.get('system.worst_disk_health')
    if health in ('Warning', 'Unhealthy'):
        add('disk-health', 'Back up before investigating drive health further',
            f"A drive reports health {health}. Reported health is a vendor summary, not a prediction, "
            'but it is reason enough to confirm backups first.',
            'low', 'system.worst_disk_health', 'system.disk_wear_percent',
            'system.disk_read_errors', 'system.disk_write_errors')

    if evidence.get('system.has_rotational_disk'):
        add('rotational-disk', 'Check which workload actually sits on the rotational drive',
            'At least one rotational drive is present. Moving a latency-sensitive workload to solid-state '
            'storage usually helps more than any setting change, but only if that workload is really there.',
            'low', 'system.has_rotational_disk', 'system.disk_count')

    if evidence.get('system.automatic_pagefile') is False:
        add('pagefile-manual', 'Re-check the manual virtual memory setting against current memory use',
            'Virtual memory is configured manually. A fixed size set for an older configuration can '
            'constrain the system; compare it against observed peak usage before changing it.',
            'moderate', 'system.automatic_pagefile', 'system.pagefile_peak_mib',
            'system.memory_total_gb')

    if not out and evidence:
        add('review-evidence', 'Review the collected evidence; no deterministic rule matched',
            'Nothing in the collected evidence crossed a deterministic threshold. That is not a clean '
            'bill of health: reproduce the symptom while measuring the connection it actually uses.',
            'low', *sorted(evidence))

    return out[:limit]


def describe(evidence):
    """Human-readable `key: label = value` lines, used in the prompt and in docs."""
    return [f'{key} ({LABELS[key]}): {value}' for key, value in sorted(evidence.items())]
