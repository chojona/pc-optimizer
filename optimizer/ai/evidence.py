"""Allowlisted, redacted evidence extraction.

This module is the privacy boundary in the strong sense: identifiers are not
collected, so there is nothing to leak later. Only numbers, booleans and values
from closed enumerations are accepted, every number is range-checked, and any
key the allowlist does not name is ignored. Callers may therefore pass a larger
envelope (a whole run record, say) without widening what reaches the model.

Read-only everywhere. Nothing here mutates the snapshot or the network result.
"""
import math

from . import privacy

#: Stable evidence identifier -> short, unit-bearing label shown to the model and
#: reused in deterministic rationales. The key set is the contract's vocabulary:
#: a model may only cite keys that are present in the collected mapping.
LABELS = {
    'system.cpu_cores': 'Physical processor cores',
    'system.cpu_threads': 'Processor threads available to Windows',
    'system.cpu_max_clock_mhz': 'Maximum reported processor clock (MHz)',
    'system.memory_total_gb': 'Installed memory (GB)',
    'system.memory_modules': 'Installed memory modules',
    'system.memory_configured_mhz': 'Lowest configured memory speed (MT/s)',
    'system.os_build': 'Windows build number',
    'system.disk_count': 'Physical drives reported',
    'system.has_rotational_disk': 'At least one rotational (HDD) drive is present',
    'system.worst_disk_health': 'Worst reported drive health',
    'system.disk_wear_percent': 'Highest reported drive wear (%)',
    'system.disk_read_errors': 'Highest reported drive read-error total',
    'system.disk_write_errors': 'Highest reported drive write-error total',
    'system.automatic_pagefile': 'Windows manages virtual memory automatically',
    'system.pagefile_peak_mib': 'Peak virtual memory used (MiB)',
    'network.link_kind': 'Active connection type',
    'network.signal_percent': 'Reported Wi-Fi signal quality (%)',
    'network.rssi_dbm': 'Received Wi-Fi signal strength (dBm)',
    'network.rx_mbps': 'Negotiated receive link speed (Mbit/s)',
    'network.tx_mbps': 'Negotiated send link speed (Mbit/s)',
    'network.band': 'Wi-Fi band in use',
    'network.channel': 'Wi-Fi channel in use',
    'network.cochannel_peers': 'Other access points cached on the same band and channel',
    'network.power_savings_enabled': 'Adapter idle power-saving properties are enabled',
    'diagnostic.fault': 'Deterministic fault classification',
    'diagnostic.confidence': 'Deterministic confidence label (heuristic, not a probability)',
    'diagnostic.aligned_rounds': 'Aligned probe rounds analysed',
    'diagnostic.shared_spikes': 'Rounds where gateway and external targets spiked together',
    'diagnostic.external_only_spikes': 'Rounds where only external targets spiked',
    'diagnostic.gateway_only_spikes': 'Rounds where only the gateway spiked',
    'diagnostic.gateway_latency_ms': 'Mean gateway response time (ms)',
    'diagnostic.gateway_jitter_ms': 'Mean gateway response-time variation (ms)',
    'diagnostic.gateway_p95_ms': 'Gateway response time at the 95th percentile (ms)',
    'diagnostic.gateway_nonresponse_percent': 'Gateway probes with no reply (%)',
    'diagnostic.external_latency_ms': 'Mean external response time across targets (ms)',
    'diagnostic.external_nonresponse_percent': 'External probes with no reply (%)',
    'diagnostic.signal_pearson_r': 'Correlation of Wi-Fi signal quality with gateway response time',
    'benchmark.download_mbps': 'Measured download speed (Mbit/s)',
    'benchmark.upload_mbps': 'Measured upload speed (Mbit/s)',
    'benchmark.dns_ms': 'Name lookup time with the configured resolver (ms)',
    'benchmark.dns_failure_percent': 'Name lookups that failed (%)',
    'benchmark.download_loaded_increase_ms': 'Extra response time during download (ms)',
    'benchmark.upload_loaded_increase_ms': 'Extra response time during upload (ms)',
    'benchmark.idle_background_mbps': 'Background traffic observed while idle (Mbit/s)',
    'benchmark.stable_path': 'The network route stayed the same for the whole test',
}

#: Lowest-value keys first. Used only to trim a prompt that would exceed the
#: configured character budget, so trimming is deterministic rather than arbitrary.
TRIM_ORDER = (
    'system.memory_modules', 'system.cpu_max_clock_mhz', 'system.memory_configured_mhz',
    'system.os_build', 'system.pagefile_peak_mib', 'system.disk_count',
    'network.channel', 'network.band', 'network.rx_mbps', 'network.tx_mbps',
    'benchmark.idle_background_mbps', 'benchmark.dns_failure_percent', 'benchmark.dns_ms',
    'diagnostic.gateway_p95_ms', 'diagnostic.signal_pearson_r',
)

LINK_KINDS = ('Wi-Fi', 'Ethernet', 'Other / virtual')
BANDS = ('2.4 GHz', '5 GHz', '6 GHz')
HEALTH = ('Healthy', 'Warning', 'Unhealthy')
ROTATIONAL = ('HDD', '3', 'Rotational')
POWER_PROPERTIES = ('SelectiveSuspend', 'DeviceSleepOnDisconnect')


def _number(value, low, high, digits=None):
    """Coerce to a finite in-range number, or None. Booleans are not numbers here."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        return None
    if digits is None:
        return int(value)
    rounded = round(value, digits)
    return int(rounded) if digits == 0 else rounded


def _flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
        return value.strip().lower() == 'true'
    return None


def _enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else None


def _slug(value):
    """Accept a short lowercase identifier only, so a stray string cannot become prose."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if 1 <= len(text) <= 40 and text[0].isalpha() and all(
            c.isalpha() and c.islower() or c.isdigit() or c == '_' for c in text):
        return text
    return None


def _rows(value):
    if isinstance(value, list):
        return [r for r in value if isinstance(r, dict)]
    return [value] if isinstance(value, dict) else []


def _best(rows, key, pick, low, high, digits=None):
    values = [v for v in (_number(r.get(key), low, high, digits) for r in rows) if v is not None]
    return pick(values) if values else None


def _section(container, name):
    """Return `container[name]` when it is a dict, else the container itself.

    Supports both documented snapshot shapes: a labelled envelope
    (`{'inventory': {...}}`) and inventory keys merged at the top level.
    """
    if not isinstance(container, dict):
        return {}
    nested = container.get(name)
    return nested if isinstance(nested, dict) else container


def _system(inventory, out):
    cpu = _rows(inventory.get('cpu'))
    out['system.cpu_cores'] = _best(cpu, 'NumberOfCores', max, 1, 1024)
    out['system.cpu_threads'] = _best(cpu, 'NumberOfLogicalProcessors', max, 1, 4096)
    out['system.cpu_max_clock_mhz'] = _best(cpu, 'MaxClockSpeed', max, 100, 20000)
    memory = _rows(inventory.get('memory'))
    capacities = [_number(r.get('Capacity'), 1, 2**44) for r in memory]
    total = sum(c for c in capacities if c)
    out['system.memory_total_gb'] = _number(total / 1e9, .5, 8192, 1) if total else None
    out['system.memory_modules'] = len(memory) or None
    out['system.memory_configured_mhz'] = _best(memory, 'ConfiguredClockSpeed', min, 100, 20000)
    os_rows = _rows(inventory.get('os'))
    out['system.os_build'] = _best(os_rows, 'BuildNumber', max, 1000, 999999)
    disks = _rows(inventory.get('disks'))
    out['system.disk_count'] = len(disks) or None
    if disks:
        out['system.has_rotational_disk'] = any(
            str(d.get('MediaType')).strip() in ROTATIONAL for d in disks)
        reported = [_enum(str(d.get('HealthStatus')), HEALTH) for d in disks]
        known = [h for h in reported if h]
        if known:
            out['system.worst_disk_health'] = max(known, key=HEALTH.index)
    health = _rows(inventory.get('health'))
    out['system.disk_wear_percent'] = _best(health, 'Wear', max, 0, 100, 1)
    out['system.disk_read_errors'] = _best(health, 'ReadErrorsTotal', max, 0, 2**40)
    out['system.disk_write_errors'] = _best(health, 'WriteErrorsTotal', max, 0, 2**40)
    for row in _rows(inventory.get('pagefile_policy')):
        flag = _flag(row.get('AutomaticManagedPagefile'))
        if flag is not None:
            out['system.automatic_pagefile'] = flag
    out['system.pagefile_peak_mib'] = _best(_rows(inventory.get('pagefile_usage')),
                                            'PeakUsage', max, 0, 2**26)


def _active_adapter(network):
    """Mirror `optimizer.network.active_adapter` without importing GUI-adjacent code."""
    index = (network.get('route') or {}).get('InterfaceIndex')
    for adapter in _rows(network.get('adapters')):
        if adapter.get('index') == index:
            return adapter
    return None


def _network(network, out):
    adapter = _active_adapter(network)
    if not adapter:
        return
    out['network.link_kind'] = _enum(adapter.get('kind'), LINK_KINDS)
    power = adapter.get('power')
    if isinstance(power, dict):
        out['network.power_savings_enabled'] = any(
            power.get(prop) == 'Enabled' for prop in POWER_PROPERTIES)
    wifi = adapter.get('wifi')
    if not isinstance(wifi, dict):
        return
    out['network.signal_percent'] = _number(wifi.get('signal_percent'), 0, 100)
    out['network.rssi_dbm'] = _number(wifi.get('rssi_dbm'), -120, 0)
    out['network.rx_mbps'] = _number(wifi.get('rx_mbps'), 0, 100000, 1)
    out['network.tx_mbps'] = _number(wifi.get('tx_mbps'), 0, 100000, 1)
    out['network.band'] = _enum(wifi.get('band'), BANDS)
    out['network.channel'] = _number(wifi.get('channel'), 1, 400)
    nearby = _rows(wifi.get('nearby'))
    if nearby:
        # Count only; BSSIDs are identifiers and are never collected.
        out['network.cochannel_peers'] = sum(
            1 for b in nearby
            if b.get('bssid') != wifi.get('bssid')
            and b.get('band') == wifi.get('band')
            and b.get('channel') == wifi.get('channel'))


def _diagnostic(diagnostic, out):
    out['diagnostic.fault'] = _slug(diagnostic.get('fault'))
    out['diagnostic.confidence'] = _slug(diagnostic.get('confidence'))
    for key, field in (('aligned_rounds', 'aligned_rounds'), ('shared_spikes', 'shared_spikes'),
                       ('external_only_spikes', 'external_only_spikes'),
                       ('gateway_only_spikes', 'gateway_only_spikes')):
        out['diagnostic.' + key] = _number(diagnostic.get(field), 0, 10**7)
    stats = diagnostic.get('statistics')
    stats = stats if isinstance(stats, dict) else {}
    gateway = stats.get('gateway') if isinstance(stats.get('gateway'), dict) else {}
    out['diagnostic.gateway_latency_ms'] = _number(gateway.get('latency_ms'), 0, 600000, 1)
    out['diagnostic.gateway_jitter_ms'] = _number(gateway.get('jitter_ms'), 0, 600000, 1)
    out['diagnostic.gateway_p95_ms'] = _number(gateway.get('p95_ms'), 0, 600000, 1)
    out['diagnostic.gateway_nonresponse_percent'] = _number(
        gateway.get('nonresponse_percent'), 0, 100, 1)
    external = [v for k, v in stats.items() if k != 'gateway' and isinstance(v, dict)]
    latencies = [_number(v.get('latency_ms'), 0, 600000, 1) for v in external]
    latencies = [v for v in latencies if v is not None]
    if latencies:
        out['diagnostic.external_latency_ms'] = round(sum(latencies) / len(latencies), 1)
    nonresponses = [_number(v.get('nonresponse_percent'), 0, 100, 1) for v in external]
    nonresponses = [v for v in nonresponses if v is not None]
    if nonresponses:
        out['diagnostic.external_nonresponse_percent'] = round(max(nonresponses), 1)
    signal = diagnostic.get('signal')
    if isinstance(signal, dict):
        out['diagnostic.signal_pearson_r'] = _number(signal.get('pearson_r'), -1, 1, 2)


def _benchmark(benchmark, out):
    results = benchmark.get('results')
    results = results if isinstance(results, dict) else {}
    ranges = {
        'download_mbps': (0, 10**6, 1), 'upload_mbps': (0, 10**6, 1),
        'dns_ms': (0, 600000, 1), 'dns_failure_percent': (0, 100, 1),
        'download_loaded_increase_ms': (-600000, 600000, 1),
        'upload_loaded_increase_ms': (-600000, 600000, 1),
    }
    for name, (low, high, digits) in ranges.items():
        row = results.get(name)
        value = row.get('value') if isinstance(row, dict) else row
        out['benchmark.' + name] = _number(value, low, high, digits)
    out['benchmark.idle_background_mbps'] = _number(
        benchmark.get('idle_background_mbps'), 0, 10**6, 2)
    out['benchmark.stable_path'] = _flag(benchmark.get('stable_path'))


def collect(snapshot, network_result=None):
    """Build the redacted evidence mapping for `snapshot` and `network_result`.

    Returns a new dict of stable identifier -> number, bool or enumerated string.
    Keys with no usable value are omitted entirely, so `evidence` in the public
    result is exactly the evidence that existed and was used.
    """
    out = {}
    _system(_section(snapshot, 'inventory'), out)
    network = snapshot.get('network')
    _network(network if isinstance(network, dict) else snapshot, out)
    benchmark = snapshot.get('benchmark')
    if isinstance(benchmark, dict):
        _benchmark(benchmark, out)
    if isinstance(network_result, dict):
        nested = network_result.get('diagnostic')
        _diagnostic(nested if isinstance(nested, dict) else network_result, out)
    clean = {}
    for key, value in out.items():
        if value is None or key not in LABELS:
            continue
        clean[key] = privacy.scrub(value) if isinstance(value, str) else value
    return clean
