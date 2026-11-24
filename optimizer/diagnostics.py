"""Pure, conservative analysis of timestamped ICMP rounds; never changes settings."""
from dataclasses import asdict, dataclass
import ipaddress
import math
import statistics


@dataclass(frozen=True)
class DiagnosticConfig:
    window_seconds: int = 120
    min_samples: int = 20
    external_targets: tuple = ('1.1.1.1', '8.8.8.8', '9.9.9.9')
    alignment_seconds: float = .15
    spike_floor_ms: float = 10.0
    min_spikes: int = 3

    def __post_init__(self):
        object.__setattr__(self, 'external_targets', tuple(self.external_targets))
        if not 10 <= self.window_seconds <= 3600 or not 3 <= self.min_samples <= 1000:
            raise ValueError('Window must be 10–3600 seconds; minimum samples 3–1000')
        if not 2 <= len(self.external_targets) <= 5 or len(set(self.external_targets)) != len(self.external_targets):
            raise ValueError('Choose 2–5 distinct external IPv4 probe targets')
        for target in self.external_targets:
            if ipaddress.ip_address(target).version != 4:
                raise ValueError('Only IPv4 probe targets are supported')
        if not 0 < self.alignment_seconds <= 1 or self.spike_floor_ms <= 0 or self.min_spikes < 1:
            raise ValueError('Invalid alignment or spike thresholds')

    def payload(self):
        return asdict(self)


def quantile(values, fraction):
    """Empirical nearest-rank percentile, including the observed maximum at P100."""
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def latency_stats(values, minimum=20):
    good = [v for v in values if v is not None]
    # Never join across a missing response when calculating consecutive RTT variation.
    changes = [abs(b - a) for a, b in zip(values, values[1:]) if a is not None and b is not None]
    return dict(sent=len(values), received=len(good), sufficient=len(good) >= minimum,
        latency_ms=statistics.mean(good) if good else None,
        p50_ms=quantile(good, .50), p95_ms=quantile(good, .95), p99_ms=quantile(good, .99),
        max_ms=max(good) if good else None,
        jitter_ms=statistics.mean(changes) if changes else None,
        jitter_p95_ms=quantile(changes, .95), jitter_pairs=len(changes),
        jitter_definition='Mean absolute consecutive successful RTT difference; gaps break pairs (not one-way IPDV).',
        nonresponse_percent=100 * (len(values) - len(good)) / len(values) if values else None,
        # Compatibility field only: ICMP nonresponse, never application packet loss.
        loss_percent=100 * (len(values) - len(good)) / len(values) if values else None,
        application_packet_loss=None,
        tail_note='P99 is descriptive and unstable with fewer than 100 replies' if len(good) < 100 else
                  'Descriptive sample percentiles; no population confidence interval')


def spike_flags(rounds, target, config):
    history, flags = [], {}
    for i, row in enumerate(rounds):
        value = row['probes'].get(target, {}).get('ms')
        if value is None:
            continue
        if len(history) >= config.min_samples:
            median = statistics.median(history)
            mad = statistics.median(abs(v - median) for v in history)
            threshold = median + max(config.spike_floor_ms, 3 * 1.4826 * mad, .5 * median)
            flags[i] = value > threshold
        history.append(value)
    return flags


def pearson(pairs, minimum):
    if len(pairs) < minimum:
        return None
    xs, ys = zip(*pairs)
    mx, my = statistics.mean(xs), statistics.mean(ys)
    xx = sum((x - mx)**2 for x in xs)
    yy = sum((y - my)**2 for y in ys)
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(xx * yy) if xx and yy else None


def analyze(rounds, config):
    targets = ['gateway', *config.external_targets]
    stats = {}
    for t in targets:
        observations = [r['probes'].get(t) for r in rounds]
        attempts = [p for p in observations if p and not p.get('error')]
        # Preserve missing/provider-error positions for jitter while keeping provider
        # errors out of the ICMP nonresponse denominator.
        st = latency_stats([p.get('ms') if p and not p.get('error') else None
                            for p in observations], config.min_samples)
        st['sent'] = len(attempts)
        st['provider_errors'] = sum(bool(p and p.get('error')) for p in observations)
        st['nonresponse_percent'] = (100 * sum(p['ms'] is None for p in attempts) / len(attempts)
                                     if attempts else None)
        st['loss_percent'] = st['nonresponse_percent']
        stats[t] = st
    flags = {t: spike_flags(rounds, t, config) for t in targets}
    aligned, shared, external_only, gateway_only = 0, 0, 0, 0
    target_evidence = {t: dict(aligned=0, shared_spikes=0, external_only_spikes=0) for t in config.external_targets}
    for i, row in enumerate(rounds):
        usable = []
        for target in config.external_targets:
            g, e = row['probes'].get('gateway', {}), row['probes'].get(target, {})
            if (i in flags['gateway'] and i in flags[target] and
                    abs(g['start'] - e['start']) <= config.alignment_seconds):
                usable.append(target)
                ev = target_evidence[target]
                ev['aligned'] += 1
                ev['shared_spikes'] += int(flags['gateway'][i] and flags[target][i])
                ev['external_only_spikes'] += int(not flags['gateway'][i] and flags[target][i])
        # Two external paths must agree within the same aligned round.
        if len(usable) < 2:
            continue
        aligned += 1
        external_spikes = sum(flags[t][i] for t in usable)
        shared += int(flags['gateway'][i] and external_spikes >= 2)
        external_only += int(not flags['gateway'][i] and external_spikes >= 2)
        gateway_only += int(flags['gateway'][i] and external_spikes == 0)
    enough = aligned >= config.min_samples
    fault, confidence = 'insufficient_evidence', 'insufficient'
    alternatives = ['ICMP filtering or control-plane rate limiting', 'Host scheduling, VPN or background traffic',
                    'External paths may share infrastructure; targets are not independent trials']
    recommendation = 'Keep measuring; collect the configured minimum of aligned successful rounds after baseline warm-up.'
    if enough:
        fault, confidence = 'no_repeated_spikes', 'low'
        recommendation = 'No repeated aligned spike pattern detected. Reproduce the application symptom while measuring its own connection.'
        if shared >= config.min_spikes and external_only >= config.min_spikes:
            fault = 'conflicting_evidence'
            recommendation = 'Mixed shared and external-only spikes: repeat at idle, then compare a manual Ethernet trial and application telemetry.'
        elif shared >= config.min_spikes:
            fault, confidence = 'shared_path_suspected', 'moderate'
            recommendation = 'Shared gateway/external spikes: check local traffic and router load; compare a manual Ethernet trial under matched conditions.'
        elif external_only >= config.min_spikes:
            fault, confidence = 'beyond_gateway_suspected', 'moderate'
            recommendation = 'Multiple external targets spike while gateway stays stable: compare at idle and retain timestamps for ISP/application-path investigation.'
        elif gateway_only >= config.min_spikes:
            fault = 'gateway_icmp_only'
            recommendation = 'Gateway-only spikes: verify application behavior before changing anything; router ICMP handling may differ from forwarding.'
        elif any(sum(flags[t].values()) >= config.min_spikes for t in config.external_targets):
            fault = 'target_specific'
            recommendation = 'A target-specific pattern needs another endpoint and application-path evidence before attributing it to the access link.'
    nonresponses = {t: s['nonresponse_percent'] for t, s in stats.items() if s['sent'] >= config.min_samples and s['nonresponse_percent']}
    if nonresponses and fault in ('no_repeated_spikes', 'insufficient_evidence'):
        fault, confidence = 'icmp_nonresponses', 'low'
        recommendation = 'ICMP nonresponses observed: check actual application failures and another protocol. This does not confirm application packet loss.'
    signal_pairs = []
    for r in rounds:
        p = r['probes'].get('gateway', {})
        s = r.get('signal_percent')
        if (s is not None and p.get('ms') is not None and not p.get('error') and
                abs(r.get('signal_at', -1e9) - p['start']) <= 2):
            signal_pairs.append((s, p['ms']))
    signal_r = pearson(signal_pairs, config.min_samples)
    return dict(fault=fault, confidence=confidence, statistics=stats, aligned_rounds=aligned,
        shared_spikes=shared, external_only_spikes=external_only, gateway_only_spikes=gateway_only,
        targets=target_evidence, nonresponses=nonresponses, recommendation=recommendation,
        alternatives=alternatives, signal=dict(pairs=len(signal_pairs), pearson_r=signal_r,
            interpretation='Signal quality % versus gateway RTT; constant/insufficient data is unavailable. Correlation does not establish causation; cached RSSI is excluded.'),
        limitations='Heuristic confidence, not a probability. Route identity follows 1.1.1.1; policy/VPN routes to other targets may differ. RTT combines both directions. Stable gateway ICMP cannot exclude a local forwarding fault. No application-level packet loss measurement is available.')
