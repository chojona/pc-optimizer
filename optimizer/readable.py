"""Local, deterministic wording for diagnostic data; original values stay intact."""
import re


LABELS = {
    'cpu': 'Processor (CPU)', 'gpu': 'Graphics processor (GPU)',
    'ram': 'Working memory (RAM)', 'os': 'Windows', 'bios': 'Motherboard firmware (BIOS)',
    'board': 'Motherboard', 'disks': 'Storage drives', 'health': 'Drive health readings',
    'power': 'Power settings', 'compiler': 'C++ compiler', 'windbg': 'Crash debugger',
    'pagefile_policy': 'Virtual memory policy (disk space used when RAM fills)',
    'pagefile_usage': 'Virtual memory usage', 'pagefile_settings': 'Manual virtual memory settings',
    'AutomaticManagedPagefile': 'Windows manages virtual memory automatically',
    'NumberOfCores': 'Physical processor cores',
    'NumberOfLogicalProcessors': 'Processor threads available to Windows',
    'MaxClockSpeed': 'Maximum reported clock speed (MHz)',
    'ConfiguredClockSpeed': 'Configured memory speed (MT/s)',
    'Capacity': 'Memory capacity', 'AdapterRAM': 'Reported graphics memory',
    'Size': 'Drive capacity', 'AllocatedBaseSize': 'Allocated virtual memory (MiB)',
    'CurrentUsage': 'Virtual memory in use (MiB)', 'PeakUsage': 'Peak virtual memory usage (MiB)',
    'InitialSize': 'Initial virtual memory size (MiB)', 'MaximumSize': 'Maximum virtual memory size (MiB)',
    'SMBIOSBIOSVersion': 'Firmware version', 'OSArchitecture': 'Windows architecture',
    'HealthStatus': 'Reported drive health', 'OperationalStatus': 'Reported operating state',
    'ReadErrorsTotal': 'Reported read errors', 'WriteErrorsTotal': 'Reported write errors',
    'PowerOnHours': 'Hours powered on', 'Temperature': 'Temperature (°C)',
    'DeviceID': 'Device identifier', 'DeviceId': 'Device identifier',
    'DriverProviderName': 'Driver provider', 'IsSigned': 'Driver is digitally signed',
    'Id': 'Event identifier', 'ProviderName': 'Event source',
    'LevelDisplayName': 'Event severity', 'Type': 'Reported type code',
    'ssid': 'Wi-Fi network name (SSID)', 'bssid': 'Wi-Fi access point identifier (BSSID)',
    'pnp_id': 'Windows device identifier', 'guid': 'Unique identifier',
    'dns': 'Website name lookup (DNS)', 'dns_ms': 'Website name lookup time (ms)',
    'dns_failure_percent': 'Website name lookups that failed (%)',
    'latency_ms': 'Response time (ms)', 'jitter_ms': 'Variation in response time (ms)',
    'loss_percent': 'Probes with no reply (%)',
    'gateway': 'Router / gateway', 'external': 'External internet target',
    'download_mbps': 'Download speed (Mbit/s)', 'upload_mbps': 'Upload speed (Mbit/s)',
    'signal_percent': 'Reported Wi-Fi signal quality (%)',
    'rssi_dbm': 'Received Wi-Fi signal strength (dBm)',
    'rx_mbps': 'Negotiated receive link speed (Mbit/s)',
    'tx_mbps': 'Negotiated send link speed (Mbit/s)',
    'link_bps': 'Negotiated link speed (bits/s)',
    'SelectiveSuspend': 'Allow the adapter to enter a low-power state while idle',
    'DeviceSleepOnDisconnect': 'Allow the adapter to sleep when disconnected',
    'stable_path': 'Network route stayed the same during the test',
    'saturation_verified': 'The test confirmed that the connection was fully loaded',
    'loaded': 'Response time while transfers were running',
    'increase_ms': 'Extra response time during transfers (ms)',
    'p95_ms': 'Response time at the 95th percentile (ms; 95% of replies were at or below this)',
    'cv': 'Relative variation between repeated samples (fraction)',
    'stdev': 'Spread of repeated measurements (standard deviation)',
    'higher': 'A higher result is better', 'complete': 'All requested tests completed',
    'verified_by_app': 'Independently verified by this app',
    'user_reports_completed': 'You reported a successful transition',
    'boot_changed': 'Windows boot time changed',
    'wall_elapsed_seconds': 'Elapsed seconds (includes time off / asleep and your delay)',
    'new_events': 'New Windows events (do not establish the cause)',
    'cpu_percent_samples': 'Processor usage samples (%)', 'memory_percent': 'Memory used (%)',
    'disk_read_latency_ms': 'Average disk read time across devices (ms)',
    'disk_write_latency_ms': 'Average disk write time across devices (ms)',
    'PagesInputPersec': 'Memory pages read from disk per second',
    'PagesOutputPersec': 'Memory pages written to disk per second',
    'PageReadsPersec': 'Disk read operations for memory pages per second',
    'PageWritesPersec': 'Disk write operations for memory pages per second',
    'AvailableMBytes': 'Available memory (MiB)', 'CommittedBytes': 'Committed memory (bytes)',
    'CommitLimit': 'Memory commitment limit (bytes)',
    'payload': 'Recorded details', 'optimization_state': 'Action history at test time',
    'revert': 'Restoring a saved setting', 'previous': 'Previous saved value',
    'target': 'Requested value', 'rollback': 'Saved setting for restoration',
    'balanced': 'Balanced power plan', 'performance': 'High performance power plan',
    'storage': 'Windows drive maintenance', 'pagefile': 'Windows-managed virtual memory',
    'integrity': 'Windows system file verification', 'image_health': 'Windows image health scan',
    'cpu_single': 'Processor test with one worker', 'cpu_multi': 'Processor test with multiple workers',
    'compile': 'C++ compilation', 'idle': 'Idle resource use', 'boot': 'Windows startup time',
}

ACTION_LABELS = {
    'balanced': 'Balanced power plan', 'performance': 'High performance power plan',
    'dns': 'Clear the cached website name lookups (DNS cache)',
    'storage': 'Windows drive maintenance', 'pagefile': 'Windows-managed virtual memory',
    'integrity': 'Windows system file verification', 'image_health': 'Windows image health scan',
    'close_process': 'Close an application', 'application': 'Application operation',
}


def readable_label(key):
    """Translate known fields and separate words in unfamiliar field names."""
    key = str(key)
    if key in LABELS:
        return LABELS[key]
    if key.endswith('_error'):
        return readable_label(key[:-6]) + ' reading error'
    for suffix, explanation in (
        ('_loaded_increase_ms', 'extra response time during transfers (ms)'),
        ('_jitter_ms', 'variation in response time (ms)'),
        ('_loss_percent', 'probes with no reply (%)'),
    ):
        if key.endswith(suffix):
            return readable_label(key[:-len(suffix)]) + ': ' + explanation
    words = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', key.replace('_', ' '))
    words = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', words)
    return words[:1].upper() + words[1:]


def _value(value, key):
    if value is None:
        return 'Unavailable (no value reported)'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    if isinstance(value, (int, float)):
        if key in ('Capacity', 'AdapterRAM', 'Size') and value >= 0:
            return f'{value / 2**30:,.2f} GiB'
        return str(value)
    if key == 'status':
        return {'started': 'Started; no completion recorded in this entry',
                'applied': 'Completed; review the recorded verification output',
                'reverted': 'Saved setting restored', 'failed': 'Could not complete',
                'cancelled': 'Cancelled'}.get(str(value), str(value))
    if key == 'action':
        return ACTION_LABELS.get(str(value), str(value))
    return str(value)


def explain_result(data):
    """Render all nested evidence, including errors and limits, without guessing outcomes."""
    def lines(value, depth=0, key=''):
        prefix = '  ' * depth
        if isinstance(value, dict):
            if not value:
                return [prefix + 'No details recorded.']
            result = []
            for field, item in value.items():
                name = prefix + readable_label(field) + ':'
                if isinstance(item, (dict, list, tuple)):
                    result.append(name)
                    result.extend(lines(item, depth + 1, field))
                else:
                    result.append(name + ' ' + _value(item, field))
            return result
        if isinstance(value, (list, tuple)):
            if not value:
                return [prefix + 'No entries recorded.']
            result = []
            for index, item in enumerate(value, 1):
                if isinstance(item, (dict, list, tuple)):
                    result.append(prefix + f'Entry {index}:')
                    result.extend(lines(item, depth + 1, key))
                else:
                    result.append(prefix + '• ' + _value(item, key))
            return result
        return [prefix + _value(value, key)]
    return '\n'.join(lines(data))


def explain_error(details):
    """Keep the error's message visible while moving Python stack frames to details."""
    last = next((line.strip() for line in reversed(details.splitlines()) if line.strip()), '')
    message = re.sub(r'^(?:[\w.]+(?:Error|Exception)|Cancelled):\s*', '', last)
    return 'The operation could not finish.\n\n' + (message or 'No error message was reported.')
