"""Network diagnostics, bounded benchmarks and explicitly approved reversible actions.

No registry/TCP tuning, adapter restart, driver installation or security changes.
"""
import base64
import copy
import ctypes
import math
import os
import socket
import statistics
import threading
import time
import urllib.request
import uuid
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor

import psutil

from .store import timestamp
from .telemetry import ping, network_stats
from .windows import psjson, powershell, rows, is_admin
from .wlan import read_wifi

POWER_PROPERTIES = ('SelectiveSuspend', 'DeviceSleepOnDisconnect')
BENCH_PARAMETERS = dict(protocol=1, external='1.1.1.1', probes=20, interval=.25,
                        repeats=3, download_bytes=16 * 1024**2, upload_bytes=4 * 1024**2,
                        endpoint='https://speed.cloudflare.com', dns_name='www.microsoft.com')
SOURCES = {
    'Power management': 'https://learn.microsoft.com/en-us/powershell/module/netadapter/set-netadapterpowermanagement',
    'Native Wi-Fi': 'https://learn.microsoft.com/en-us/windows/win32/api/wlanapi/nf-wlanapi-wlangetnetworkbsslist',
    'Benchmark endpoint': 'https://github.com/cloudflare/speedtest',
    'Driver matching': 'https://learn.microsoft.com/en-us/windows/win32/wua_sdk/idriverupdate',
    'OEM support': 'https://www.asus.com/support/download-center/',
    'Intel support': 'https://www.intel.com/content/www/us/en/download-center/home.html',
    'Realtek support': 'https://www.realtek.com/Download/Overview?menu_id=276',
}


def adapter_inventory():
    # Each optional provider fails independently. Serialize enums explicitly, never parse display text.
    return psjson(r"""
      $adapters=@(Get-NetAdapter -IncludeHidden | ForEach-Object {
        $a=$_; $r=[ordered]@{guid=[string]$a.InterfaceGuid; index=$a.ifIndex; name=$a.Name;
          model=$a.InterfaceDescription; status=[string]$a.Status; physical=$a.HardwareInterface;
          media=[string]$a.NdisPhysicalMedium; link_bps=[double]$a.ReceiveLinkSpeed;
          driver=$a.DriverVersion; pnp_id=$a.PnPDeviceID; mac=$a.MacAddress}
        try {$r.power=($a | Get-NetAdapterPowerManagement | Select-Object -Property @(
          @{n='SelectiveSuspend';e={[string]$_.SelectiveSuspend}},
          @{n='DeviceSleepOnDisconnect';e={[string]$_.DeviceSleepOnDisconnect}},
          @{n='AllowComputerToTurnOffDevice';e={[string]$_.AllowComputerToTurnOffDevice}},
          @{n='WakeOnMagicPacket';e={[string]$_.WakeOnMagicPacket}},
          @{n='WakeOnPattern';e={[string]$_.WakeOnPattern}}))} catch {$r.power_error=$_.Exception.Message}
        try {$r.advanced=@($a | Get-NetAdapterAdvancedProperty -AllProperties |
          Select-Object DisplayName,DisplayValue,RegistryKeyword,RegistryValue,ValidDisplayValues,ValidRegistryValues)}
          catch {$r.advanced_error=$_.Exception.Message}
        try {$r.dns=@(Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex |
          Select-Object AddressFamily,ServerAddresses)} catch {$r.dns_error=$_.Exception.Message}
        [pscustomobject]$r
      })
      $route=$null; $routeError=$null
      try {$r=Find-NetRoute -RemoteIPAddress '1.1.1.1'; $route=$r |
        Where-Object {$_.PSObject.Properties['NextHop']} |
        Select-Object -First 1 InterfaceIndex,NextHop,DestinationPrefix,RouteMetric}
        catch {$routeError=$_.Exception.Message}
      [pscustomobject]@{adapters=$adapters; route=$route; route_error=$routeError}
    """, 45) or {'adapters': [], 'route': None}


def discover():
    try:
        out = adapter_inventory()
    except Exception as exc:
        out = {'adapters': [], 'route': None, 'error': str(exc)}
    out.update(captured_at=timestamp(), wifi=read_wifi())
    for a in out.get('adapters', []):
        a['kind'] = 'Wi-Fi' if str(a.get('media')) in ('9', 'Native802_11', 'WirelessLan', '1') else (
            'Ethernet' if str(a.get('media')) in ('14', '802_3') else 'Other / virtual')
        for w in out['wifi'].get('interfaces', []):
            if normalize_guid(a['guid']) == normalize_guid(w['guid']):
                a['kind'], a['wifi'] = 'Wi-Fi', w
    return out


def normalize_guid(value):
    return str(uuid.UUID(str(value).strip('{}')))


def active_adapter(snapshot):
    index = (snapshot.get('route') or {}).get('InterfaceIndex')
    return next((a for a in snapshot.get('adapters', []) if a['index'] == index), None)


def gateway(snapshot):
    value = (snapshot.get('route') or {}).get('NextHop')
    return value if value and value != '0.0.0.0' else None


def current_route():
    """Cheap route lookup for every probe cycle, including VPN / adapter handovers."""
    if os.name != 'nt':
        return None
    class Route(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint32) for name in (
            'dest', 'mask', 'policy', 'next_hop', 'index', 'type', 'proto', 'age',
            'next_hop_as', 'metric1', 'metric2', 'metric3', 'metric4', 'metric5')]
    api = ctypes.WinDLL('iphlpapi')
    api.GetBestRoute.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Route)]
    route = Route()
    code = api.GetBestRoute(int.from_bytes(socket.inet_aton('1.1.1.1'), 'little'), 0, ctypes.byref(route))
    if code:
        return None
    return dict(InterfaceIndex=route.index,
                NextHop=socket.inet_ntoa(route.next_hop.to_bytes(4, 'little')))


def channel_summary(wifi):
    """Observed co-channel and adjacent 2.4 GHz AP counts, never airtime utilization."""
    aps = {}
    for w in wifi.get('interfaces', []):
        for b in w.get('nearby', []):
            # Deduplicate the same AP seen by multiple radios, keeping strongest observation.
            if b['bssid'] not in aps or b['rssi_dbm'] > aps[b['bssid']]['rssi_dbm']:
                aps[b['bssid']] = b
    counts = Counter((b['band'], b['channel']) for b in aps.values() if b['channel'] is not None)
    result = []
    for (band, channel), count in sorted(counts.items()):
        adjacent = sum(1 for b in aps.values() if band == b['band'] == '2.4 GHz'
                       and b['channel'] is not None and 0 < abs(channel - b['channel']) < 5)
        strongest = max(b['rssi_dbm'] for b in aps.values() if (b['band'], b['channel']) == (band, channel))
        result.append(dict(band=band, channel=channel, access_points=count,
                           adjacent_24ghz=adjacent, strongest_dbm=strongest))
    return result


class NetworkMonitor:
    def __init__(self):
        self.target_key = None
        self.samples = {'gateway': deque(maxlen=60), 'external': deque(maxlen=60)}
        self.counters = psutil.net_io_counters(pernic=True)
        self.last_time = time.monotonic()

    def sample(self, snapshot):
        snapshot = dict(snapshot, route=current_route())
        adapter = active_adapter(snapshot)
        key = ((snapshot.get('route') or {}).get('InterfaceIndex'), gateway(snapshot))
        path_changed = key != self.target_key
        if path_changed:
            for values in self.samples.values():
                values.clear()
            self.target_key = key
        targets = {'gateway': gateway(snapshot), 'external': '1.1.1.1'}
        # Separate bounded probes; missing gateway is unavailable, not 100% packet loss.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {k: pool.submit(ping, host) for k, host in targets.items() if host}
            current = {k: f.result() for k, f in futures.items()}
        out = dict(captured_at=timestamp(), targets=targets, current=current,
                   path_changed=path_changed, route=snapshot.get('route'),
                   routed_adapter=(adapter or {}).get('name'), wifi=read_wifi())
        for k in targets:
            if targets[k]:
                self.samples[k].append(current.get(k))
            out[k] = network_stats(list(self.samples[k]))
        now = time.monotonic()
        counters = psutil.net_io_counters(pernic=True)
        out['adapters'] = []
        for name, value in counters.items():
            old = self.counters.get(name)
            out['adapters'].append(dict(name=name,
                download_bps=max(0, value.bytes_recv - old.bytes_recv) / max(.01, now - self.last_time) if old else None,
                upload_bps=max(0, value.bytes_sent - old.bytes_sent) / max(.01, now - self.last_time) if old else None))
        self.counters, self.last_time = counters, now
        out['process_bandwidth'] = {'supported': False, 'reason':
            'Unavailable: no ETW byte-accounting provider is integrated. psutil socket counts and process I/O are not network bandwidth.'}
        return out


def recommendations(snapshot, observation=None, benchmark=None):
    result = []
    def card(title, evidence, benefit, risk='Low', action=None):
        result.append(dict(title=title, evidence=evidence, expected_benefit=benefit, risk=risk,
                           verification='Theoretical benefit; repeat comparable benchmarks to assess', action=action))
    a = active_adapter(snapshot)
    if not a:
        card('Resolve route detection', snapshot.get('route_error') or 'No IPv4 route to the external probe was detected.',
             'Diagnostics need a known route; IPv6-only paths are currently unsupported.')
        return result
    w = a.get('wifi', {})
    if w.get('signal_percent', 100) < 60:
        card('Improve radio placement or test Ethernet', f"{a['name']}: signal quality {w['signal_percent']}%.",
             'A stronger radio path may reduce retries and local jitter. Compare from the same location; no automatic handover.')
    peers = [b for b in w.get('nearby', []) if b.get('bssid') != w.get('bssid')
             and b.get('band') == w.get('band') and b.get('channel') == w.get('channel')]
    if peers:
        card('Review the router channel', f"{len(peers)} other cached BSS observations on channel {w.get('channel')} ({w.get('band')}).",
             'An AP channel survey may identify less contention. Counts do not measure airtime or prove congestion. Router changes require separate manual review.')
    obs = observation or {}
    g, e = obs.get('gateway', {}), obs.get('external', {})
    if g.get('sent', 0) >= 10 and (g.get('loss_percent', 0) > 0 or (g.get('jitter_ms') or 0) > 5):
        card('Investigate local path instability', f"Gateway: {g.get('loss_percent')}% unanswered, jitter {g.get('jitter_ms')} ms over {g['sent']} probes.",
             'Check cable, radio placement and gateway load before changing adapter settings. ICMP filtering or rate limiting can mimic loss.')
    if e.get('sent', 0) >= 10 and (e.get('loss_percent', 0) > 0 or (e.get('latency_ms') or 0) > 60):
        card('Check upstream load and application paths', f"External ICMP: {e.get('latency_ms')} ms, {e.get('loss_percent')}% unanswered.",
             'Test router queue management and ISP path, and monitor the actual game or broker connection separately. 1.1.1.1 is not a trading execution venue.')
    for prop in POWER_PROPERTIES:
        if (a.get('power') or {}).get(prop) == 'Enabled':
            card('Review ' + prop, f"{a['name']}: {prop} is Enabled; no power-transition fault has been established.",
                 'Disabling may help only with documented idle/resume faults and increases power use. No guaranteed latency gain; activation may require a later manual restart.',
                 'Moderate', dict(guid=a['guid'], property=prop))
    if benchmark:
        for direction in ('download', 'upload'):
            bloat = benchmark.get('loaded', {}).get(direction, {})
            if (bloat.get('increase_ms') or 0) > 15:
                card('Investigate queueing during ' + direction,
                     f"Observed loaded latency increase {bloat['increase_ms']:.1f} ms. Saturation was not verified.",
                     'Router SQM or scheduling bulk transfers outside gaming/trading sessions may help. Verify at matched load; no router setting is changed here.')
    card('Verify the exact network driver', f"Installed {a.get('model')}, driver {a.get('driver') or 'unavailable'}.",
         'Review hardware-matched Windows Update metadata and OEM release notes for relevant fixes. A newer version alone does not establish better performance.', 'Moderate')
    return result


class NetworkActions:
    """A small allowlist. Approval is mandatory even for programmatic callers."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()

    def execute(self, adapter_guid, prop, *, approved=False, revert=False):
        if not approved:
            raise PermissionError('Explicit approval is required for each network setting change')
        if prop not in POWER_PROPERTIES:
            raise ValueError('Unsupported property; security and arbitrary driver properties cannot be changed')
        adapter_guid = normalize_guid(adapter_guid)
        if not is_admin():
            raise PermissionError('Administrator rights required; restart using Activity & Settings')
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('Another network action is running')
        key = f'network:rollback:{adapter_guid}:{prop}'
        try:
            before = discover()
            a = next((a for a in before['adapters'] if normalize_guid(a['guid']) == adapter_guid), None)
            if not a or not a.get('pnp_id'):
                raise ValueError('Adapter identity unavailable; rescan before changing settings')
            previous = self.store.get(key)
            current = (a.get('power') or {}).get(prop)
            if current not in ('Enabled', 'Disabled'):
                raise ValueError('Driver does not expose this writable power setting')
            if revert:
                if not previous:
                    raise ValueError('No saved configuration to restore')
                if a['pnp_id'] != previous['pnp_id']:
                    raise ValueError('Adapter or setting changed since apply; refusing to overwrite later changes')
                if current == previous['previous']:
                    self.store.set(key, None)
                    self.store.action(key, 'reverted', {'output': 'Original configured value already present; no mutation required'})
                    return 'Original configured value already present and verified; saved rollback cleared without changing the adapter'
                if current != previous['target']:
                    raise ValueError('Adapter or setting changed since apply; refusing to overwrite later changes')
                target = previous['previous']
                if target not in ('Enabled', 'Disabled'):
                    raise ValueError('Saved value is invalid; refusing to execute an unrecognized setting')
            else:
                if previous:
                    raise ValueError('Rollback already exists; restore it before applying again')
                if current == 'Disabled':
                    return 'Already disabled; no change made'
                target = 'Disabled'
                self.store.save_run('network snapshot', before)
                # Durable original state before the first system mutation, retained on any failure.
                self.store.set(key, dict(guid=adapter_guid, property=prop, pnp_id=a['pnp_id'],
                                         previous=current, target=target, captured_at=timestamp()))
            self.store.action(key, 'started', dict(revert=revert, target=target))
            # GUID is validated and property/target are allowlisted; no wildcard name targeting.
            identity = base64.b64encode(a['pnp_id'].encode('utf-8')).decode('ascii')
            script = (f"$a=@(Get-NetAdapter -IncludeHidden | Where-Object {{[string]$_.InterfaceGuid -eq '{adapter_guid}'}}); "
                      "if($a.Count -ne 1){throw 'Adapter identity changed'}; "
                      f"$id=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{identity}')); "
                      "if($a[0].PnPDeviceID -ne $id){throw 'Adapter replaced'}; "
                      "$p=$a[0] | Get-NetAdapterPowerManagement; "
                      f"if([string]$p.{prop} -ne '{current}'){{throw 'Setting changed since snapshot'}}; "
                      f"$a[0] | Set-NetAdapterPowerManagement -{prop} {target} -NoRestart -Confirm:$false")
            powershell(script, 30)
            after = discover()
            actual = next((v for v in after['adapters'] if normalize_guid(v['guid']) == adapter_guid), {})
            self.store.save_run('network snapshot', after)
            if actual.get('pnp_id') != a['pnp_id'] or (actual.get('power') or {}).get(prop) != target:
                raise RuntimeError('Configured-state verification failed; rollback retained for recovery')
            if revert:
                self.store.set(key, None)
            out = 'Configured state verified. No adapter restart was requested. Effective behavior may require a later manual restart; no performance benefit is assumed.'
            self.store.action(key, 'reverted' if revert else 'applied', dict(output=out, target=target))
            return out
        except Exception as exc:
            self.store.action(key, 'failed', dict(error=str(exc), revert=revert))
            raise
        finally:
            self.lock.release()

    def backups(self):
        with self.store.connect() as db:
            keys = [r[0] for r in db.execute("SELECT key FROM settings WHERE key LIKE 'network:rollback:%'")]
        return [v for k in keys if (v := self.store.get(k))]


def verify_driver_updates(snapshot):
    """Official WUA applicability search, then exact hardware-ID matching, never install."""
    a = active_adapter(snapshot)
    if not a or not a.get('pnp_id'):
        raise ValueError('No routed adapter with a PnP identity is available')
    # Pass only base64 data into the PowerShell literal, not a device supplied expression.
    identity = base64.b64encode(a['pnp_id'].encode('utf-8')).decode('ascii')
    result = psjson(f"""
      $id=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{identity}'));
      $d=Get-CimInstance Win32_PnPEntity | Where-Object {{$_.PNPDeviceID -eq $id}};
      if(-not $d){{throw 'PnP device no longer present'}};
      $ids=@($d.HardwareID)+@($d.CompatibleID);
      $s=New-Object -ComObject Microsoft.Update.Session;
      $r=$s.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Driver'");
      $matches=@($r.Updates | Where-Object {{$ids -contains $_.DriverHardwareID}} | ForEach-Object {{
        [pscustomobject]@{{title=$_.Title; hardware_id=$_.DriverHardwareID; manufacturer=$_.DriverManufacturer;
          model=$_.DriverModel; driver_date=[string]$_.DriverVerDate; update_id=$_.Identity.UpdateID}}
      }});
      [pscustomobject]@{{hardware_ids=$ids; candidates=$matches; result_code=[int]$r.ResultCode}}
    """, 240) or {}
    return dict(captured_at=timestamp(), adapter=a['model'], installed_driver=a.get('driver'),
                source='Windows Update Agent; applicable metadata matched to exact PnP hardware/compatible IDs',
                verification=result, status='Candidates require OEM/OS/release-note review. No candidates does not verify latest vendor release.',
                official_sources=SOURCES)


def context(snapshot):
    """Path identity excludes the power setting under test, but retains driver and Wi-Fi path."""
    a = active_adapter(snapshot) or {}
    w = a.get('wifi', {})
    return dict(guid=a.get('guid'), pnp_id=a.get('pnp_id'), driver=a.get('driver'), kind=a.get('kind'),
                link_bps=a.get('link_bps'), gateway=gateway(snapshot), dns=a.get('dns'),
                ssid=w.get('ssid'), bssid=w.get('bssid'), channel=w.get('channel'), band=w.get('band'))


def percentile(values, fraction=.95):
    good = sorted(v for v in values if v is not None)
    return good[min(len(good) - 1, math.ceil(len(good) * fraction) - 1)] if good else None


def summarize(values):
    good = [v for v in values if v is not None]
    return dict(value=statistics.median(good) if good else None, samples=values,
                p95=percentile(values), stdev=statistics.stdev(good) if len(good) > 1 else None)


class NetworkBenchmark:
    def __init__(self, store):
        self.store = store
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set():
            raise InterruptedError('Cancelled by user; partial results saved')

    def transfer(self, direction, size):
        """Fixed HTTPS endpoint; no redirects, untrusted URLs, downloads to disk or personal data."""
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(NoRedirect())
        url = BENCH_PARAMETERS['endpoint'] + ('/__down?bytes=' + str(size) if direction == 'download' else '/__up')
        request = urllib.request.Request(url, data=b'\0' * size if direction == 'upload' else None,
                                         headers={'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
                                                  'User-Agent': 'PCOptimizer-Network/1'})
        start = time.monotonic()
        received = 0
        with opener.open(request, timeout=10) as response:
            while True:
                self.check()
                if time.monotonic() - start > 20:
                    raise TimeoutError('Transfer exceeded 20-second phase deadline')
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > (size if direction == 'download' else 1024**2):
                    raise ValueError('Endpoint exceeded response byte limit')
        if direction == 'download' and received != size:
            raise ValueError('Download size mismatch; incomplete transfer discarded')
        seconds = time.monotonic() - start
        return dict(mbps=size * 8 / max(seconds, .000001) / 1e6, seconds=seconds, bytes=size)

    def run(self, conditions, progress=lambda _: None, *, approved=False):
        if not approved:
            raise PermissionError('Approve external test traffic before starting benchmarks')
        if not conditions.strip():
            raise ValueError('Describe location, AC power, VPN and background workload for comparison')
        p = copy.deepcopy(BENCH_PARAMETERS)
        out = dict(captured_at=timestamp(), parameters=p, conditions=conditions.strip(), results={},
                   loaded={}, errors={}, complete=False, notes=[
                       'Single HTTPS stream, bounded bytes; includes TLS/server overhead and does not establish maximum line speed.',
                       'ICMP probes follow the OS IPv4 route; not bound to a selected adapter. ICMP filtering can mimic packet loss.',
                       'DNS tests use the configured OS resolver and may include cache hits; not an uncached resolver ranking.',
                       'Loaded latency compares external ICMP before and during transfer. Saturation unverified; no bufferbloat grade.',
                       'Internet conditions are uncontrolled. Observed differences do not establish causality.'])
        try:
            self.check()
            out['before'] = discover()
            if not active_adapter(out['before']):
                raise ValueError('No IPv4 route to the external probe; benchmark unsupported on this path')
            out['context'] = context(out['before'])
            out['signal_before'] = (active_adapter(out['before']) or {}).get('wifi', {}).get('signal_percent')
            baseline_adapter = active_adapter(out['before'])['name']
            idle_start = time.monotonic()
            idle_counters = psutil.net_io_counters(pernic=True).get(baseline_adapter)
            out['path_changes'] = []
            def check_path():
                route = current_route()
                expected = out['before'].get('route') or {}
                if not route or any(route.get(k) != expected.get(k) for k in ('InterfaceIndex', 'NextHop')):
                    out['path_changes'].append(dict(captured_at=timestamp(), route=route))
            progress('Measuring baseline gateway and external ICMP…')
            baseline = {'gateway': [], 'external': []}
            targets = {'gateway': gateway(out['before']), 'external': p['external']}
            with ThreadPoolExecutor(max_workers=2) as pool:
                for _ in range(p['probes']):
                    self.check()
                    check_path()
                    batch = {k: pool.submit(ping, v) for k, v in targets.items() if v}
                    for k, f in batch.items():
                        baseline[k].append(f.result())
                    self.cancel.wait(p['interval'])
            idle_after = psutil.net_io_counters(pernic=True).get(baseline_adapter)
            out['idle_background_mbps'] = (max(0, idle_after.bytes_recv + idle_after.bytes_sent -
                idle_counters.bytes_recv - idle_counters.bytes_sent) * 8 / 1e6 /
                max(.001, time.monotonic() - idle_start)) if idle_counters and idle_after else None
            out['baseline'] = {k: dict(network_stats(v), samples=v, p95_ms=percentile(v)) for k, v in baseline.items()}
            for k, v in out['baseline'].items():
                out['results'][k + '_latency_ms'] = summarize(v['samples'])
                out['results'][k + '_loss_percent'] = dict(value=v['loss_percent'], samples=[], stdev=None)
                out['results'][k + '_jitter_ms'] = dict(value=v['jitter_ms'], samples=[], stdev=None)
            progress('Measuring configured DNS resolver (cache may contribute)…')
            self.check()
            try:
                dns = rows(psjson("1..5 | ForEach-Object { $t=[Diagnostics.Stopwatch]::StartNew(); try {"
                    "Resolve-DnsName -Name 'www.microsoft.com' -Type A -DnsOnly -QuickTimeout | Out-Null; "
                    "$t.Stop(); [pscustomobject]@{ms=$t.Elapsed.TotalMilliseconds; ok=$true}} catch {"
                    "[pscustomobject]@{ms=$null; ok=$false; error=$_.Exception.Message}} }", 30))
            except Exception as exc:
                dns = []
                out['errors']['dns'] = str(exc)
            out['dns'] = dns
            out['results']['dns_ms'] = summarize([v.get('ms') if v.get('ok') else None for v in dns])
            out['results']['dns_failure_percent'] = dict(
                value=100 * sum(not v.get('ok') for v in dns) / len(dns) if dns else None,
                samples=[], stdev=None)
            for direction in ('download', 'upload'):
                self.check()
                progress('Measuring ' + direction + ' and loaded latency; bulk traffic is running…')
                loaded, transfers = [], []
                done = threading.Event()
                def probe():
                    while not done.is_set() and not self.cancel.is_set():
                        loaded.append((time.monotonic(), ping(p['external'])))
                        done.wait(.2)
                thread = threading.Thread(target=probe, daemon=True)
                start = time.monotonic()
                thread.start()
                try:
                    for _ in range(p['repeats']):
                        self.check()
                        check_path()
                        transfers.append(self.transfer(direction, p[direction + '_bytes']))
                except InterruptedError:
                    raise
                except Exception as exc:
                    out['errors'][direction] = str(exc)
                finally:
                    end = time.monotonic()
                    done.set()
                    thread.join(timeout=2)
                out['results'][direction + '_mbps'] = summarize([t['mbps'] for t in transfers])
                values = [v for t, v in loaded if t <= end]
                base = out['baseline']['external']
                duration = end - start
                valid = (not out['errors'].get(direction) and duration >= 3 and len(values) >= 8
                         and sum(v is not None for v in values) >= 8 and base['received'] >= 10)
                loaded_median = summarize(values)['value']
                idle_median = summarize(base['samples'])['value']
                increase = loaded_median - idle_median if valid else None
                out['loaded'][direction] = dict(samples=values, duration_seconds=duration, transfers=transfers,
                    stats=network_stats(values), increase_ms=increase, saturation_verified=False,
                    status='Observed loaded latency; saturation unverified' if valid else
                    'Inconclusive: transfer too short, failed, or insufficient ICMP replies; saturation unverified')
                out['results'][direction + '_loaded_increase_ms'] = dict(value=increase, samples=[], stdev=None)
            self.check()
            out['complete'] = not out['errors']
        except Exception as exc:
            out['errors']['cancelled' if self.cancel.is_set() else 'suite'] = str(exc)
        finally:
            out['after'] = discover()
            out['stable_path'] = (bool(out.get('context', {}).get('guid')) and
                                  out.get('context') == context(out['after']) and not out.get('path_changes'))
            out['signal_after'] = (active_adapter(out['after']) or {}).get('wifi', {}).get('signal_percent')
            out['id'] = self.store.save_run('network benchmark', out)
        return out


def compare_network(before, after):
    """Conservative comparisons: never infer a verified fix from a single uncontrolled pair."""
    a, b = before['payload'], after['payload']
    reasons = []
    if before['id'] == after['id']:
        reasons.append('Select two different runs')
    for key in ('parameters', 'context', 'conditions'):
        if not a.get(key) or a.get(key) != b.get(key):
            reasons.append(key + ' differs or is missing')
    if not a.get('complete') or not b.get('complete') or not a.get('stable_path') or not b.get('stable_path'):
        reasons.append('Incomplete test or route changed during measurement')
    if not all(a.get('context', {}).get(k) and b.get('context', {}).get(k) for k in ('guid', 'pnp_id', 'driver')):
        reasons.append('Adapter/driver identity unavailable')
    if a.get('context', {}).get('kind') == 'Wi-Fi' and not all(
            a.get('context', {}).get(k) and b.get('context', {}).get(k) for k in ('ssid', 'bssid', 'channel', 'band')):
        reasons.append('Wi-Fi path identity unavailable')
    traffic_a, traffic_b = a.get('idle_background_mbps'), b.get('idle_background_mbps')
    if traffic_a is None or traffic_b is None:
        reasons.append('Idle background traffic unavailable')
    elif abs(traffic_a - traffic_b) > max(1, max(traffic_a, traffic_b) * .2):
        reasons.append('Idle background traffic differs materially')
    signals = [x for v in (a, b) for x in (v.get('signal_before'), v.get('signal_after')) if x is not None]
    if signals and (len(signals) != 4 or max(signals) - min(signals) > 10):
        reasons.append('Wi-Fi signal changed or is unavailable')
    if a.get('context', {}).get('ssid') and not signals:
        reasons.append('Wi-Fi signal unavailable')
    result = []
    for name, old in a.get('results', {}).items():
        new = b.get('results', {}).get(name, {})
        x, y = old.get('value'), new.get('value')
        status = 'Not comparable' if reasons else 'Unavailable'
        delta = None
        if not reasons and x is not None and y is not None:
            delta = y - x
            # Throughput/DNS repeated samples support an observed-variation threshold, not statistical proof.
            sd = math.sqrt((old.get('stdev') or 0)**2 + (new.get('stdev') or 0)**2)
            threshold = max(abs(x) * .05, 2 * sd)
            sufficient = (len([v for v in old.get('samples', []) if v is not None]) >= 3
                          and len([v for v in new.get('samples', []) if v is not None]) >= 3)
            if not sufficient:
                status = 'Observed difference; uncertainty unavailable'
            elif abs(delta) <= threshold:
                status = 'Within observed variation'
            else:
                status = 'Observed improvement' if (delta > 0) == name.endswith('_mbps') else 'Observed regression'
        result.append(dict(metric=name, before=x, after=y, delta=delta, status=status))
    return dict(comparable=not reasons, reasons=reasons, results=result,
                conclusion='No verified causal improvement. Repeat alternating before/after trials under matched load; internet/server conditions remain uncontrolled.')
