"""Versioned, deterministic network evidence analysis. No probing or host actions."""
from ..diagnostics import analyze as analyze_diagnostics
from .validation import CONFIG_KEYS, keys, validate

__all__ = ['analyze', 'from_event']

LIMITATIONS = [
    'Confidence labels are heuristic, not measured probabilities or proof of cause.',
    'ICMP nonresponse is not application packet loss; filtering and control-plane rate limiting are alternatives.',
    'External targets can share infrastructure; RTT combines both directions. Stable gateway ICMP cannot exclude a local forwarding fault.',
    'The caller must supply one route and monotonic clock session. Policy/VPN routes to external targets may differ.',
    'IPv6-only paths, per-process bandwidth, channel airtime, throughput saturation and application loss are unsupported or unmeasured.',
    'Wi-Fi signal quality is not dBm. Correlation does not establish causation; stale signal pairs are excluded.',
]

EXPLANATIONS = {
    'insufficient_evidence': 'Too few aligned successful rounds after baseline warm-up to isolate a path pattern.',
    'no_repeated_spikes': 'No repeated aligned spikes were detected in this window. This does not establish a healthy application connection.',
    'shared_path_suspected': 'Repeated gateway and multiple external spikes coincide. A shared local path is suspected; host scheduling or ICMP handling remain alternatives.',
    'beyond_gateway_suspected': 'Multiple external targets spike together while gateway ICMP stays stable. A path beyond the gateway is suspected, but local forwarding faults remain possible.',
    'conflicting_evidence': 'Both shared and external-only spikes repeat. Mixed evidence does not isolate a single bottleneck.',
    'gateway_icmp_only': 'Gateway spikes do not repeat across external targets. Router ICMP handling may differ from application forwarding.',
    'target_specific': 'Repeated spikes affect an individual external target without a repeated multi-target pattern. This does not isolate the access link.',
    'icmp_nonresponses': 'ICMP attempts lacked responses. Compare application telemetry or another protocol before attributing application packet loss.',
}


def analyze(snapshot: dict) -> dict:
    """Analyze an agreed v1 snapshot. Malformed input raises ValueError."""
    config, fresh = validate(snapshot)
    diagnostic = analyze_diagnostics(fresh, config) if snapshot['stable_path'] else None
    evidence = dict(diagnostic=diagnostic, input_rounds=len(snapshot['rounds']),
                    analyzed_rounds=len(fresh) if diagnostic is not None else 0,
                    stale_rounds=len(snapshot['rounds']) - len(fresh))
    findings, recommendations = [], []

    def finding(identity, explanation, refs, confidence='low', severity='warning'):
        findings.append(dict(id='network.' + identity, severity=severity,
                             evidence_refs=refs, confidence=confidence, explanation=explanation))

    state = 'insufficient'
    if diagnostic is None:
        finding('unstable_path', 'Route identity changed during capture; path inference was suppressed.',
                ['/evidence/diagnostic'], 'insufficient')
        text = 'Route instability prevents path inference.'
    else:
        fault = diagnostic['fault']
        enough = diagnostic['aligned_rounds'] >= config.min_samples
        state = 'ok' if enough else 'insufficient'
        text = EXPLANATIONS[fault]
        finding(fault, text, ['/evidence/diagnostic'], diagnostic['confidence'],
                'info' if fault == 'no_repeated_spikes' else 'warning')
        if not enough and fault != 'insufficient_evidence':
            finding('insufficient_evidence', EXPLANATIONS['insufficient_evidence'],
                    ['/evidence/diagnostic/aligned_rounds'], 'insufficient')
            text = 'Insufficient aligned evidence for path inference. ' + text
        stats = diagnostic['statistics']
        if any(s['provider_errors'] for s in stats.values()):
            finding('provider_errors', 'Probe provider failures were excluded from ICMP attempts and nonresponse percentages. Missing evidence is not zero latency.',
                    ['/evidence/diagnostic/statistics'])
        if any(len(fresh) > s['sent'] + s['provider_errors'] for s in stats.values()):
            finding('missing_probes', 'Some targets were unavailable in retained rounds. Missing probes do not count as attempts or zero RTT.',
                    ['/evidence/diagnostic/statistics'])
        signal = diagnostic['signal']
        if signal['pearson_r'] is not None:
            finding('wifi_signal_correlation', 'Aligned Wi-Fi signal quality and gateway RTT have a descriptive correlation; this does not establish a radio fault.',
                    ['/evidence/diagnostic/signal'], severity='info')
        else:
            finding('wifi_signal_unavailable', 'Wi-Fi correlation is unavailable: signal pairs are missing, sparse, stale, or constant. Ethernet may have no Wi-Fi evidence.',
                    ['/evidence/diagnostic/signal'], 'insufficient', 'info')
    if evidence['stale_rounds']:
        finding('stale_data', 'Rounds older than the configured window were excluded using the supplied UTC evaluation time.',
                ['/evidence/stale_rounds'], severity='info')

    identity = 'collect_evidence'
    rationale = 'Collect a fresh stable-route window with aligned gateway and multiple external replies, then compare application telemetry. Additional probes require explicit initiation.'
    refs = ['/evidence/analyzed_rounds']
    if state == 'ok':
        fault = diagnostic['fault']
        refs = ['/evidence/diagnostic']
        identity = {'shared_path_suspected': 'compare_local_path',
                    'beyond_gateway_suspected': 'compare_external_path'}.get(fault, 'compare_application')
        rationale = diagnostic['recommendation']
    recommendations.append(dict(id='network.' + identity, rationale=rationale,
                                evidence_refs=refs, risk='low', requires_approval=True))
    return dict(schema_version=1, summary=dict(state=state, text=text), findings=findings,
                recommendations=recommendations, limitations=list(LIMITATIONS), evidence=evidence)


def from_event(event: dict, *, as_of: str) -> dict:
    """Project an existing saved diagnostic event payload, with no I/O.

    Event metadata (path, precomputed diagnostics) is deliberately not trusted as
    inference. The validated raw rounds are the sole statistical source.
    """
    if type(event) is not dict:
        raise ValueError('Expected a diagnostic event payload')
    required = {'captured_at', 'config', 'rounds', 'stable_round'}
    if not required <= event.keys():
        raise ValueError('Diagnostic event is missing required fields')
    snapshot = dict(schema_version=1, captured_at=event['captured_at'], as_of=as_of,
                    stable_path=event['stable_round'], config=event['config'], rounds=event['rounds'])
    # DiagnosticConfig.payload uses a tuple in live Python and a list in JSON.
    # Only this explicit legacy adapter normalizes that documented representation.
    if type(snapshot['config']) is dict:
        keys(snapshot['config'], CONFIG_KEYS)
        snapshot['config'] = dict(snapshot['config'])
        targets = snapshot['config'].get('external_targets')
        if type(targets) is tuple:
            if not 2 <= len(targets) <= 5:
                raise ValueError('Expected 2–5 external targets')
            snapshot['config']['external_targets'] = list(targets)
    validate(snapshot)
    # Return independent plain JSON containers; callers cannot mutate saved data.
    import json
    return json.loads(json.dumps(snapshot, allow_nan=False))
