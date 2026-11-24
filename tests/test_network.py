import copy
import ctypes

import pytest

from optimizer import network
from optimizer.store import Store
from optimizer.wlan import frequency_channel, BSS, Association

GUID = 'd8c53235-56a9-462a-89b2-d752a550068a'


@pytest.fixture
def snapshot():
    return dict(captured_at='2026-11-24T00:00:00+00:00',
        adapters=[dict(guid=GUID, index=18, name='Wi-Fi', model='Test radio', status='Up',
            physical=True, kind='Wi-Fi', media='9', link_bps=866000000, driver='1.2.3',
            pnp_id=r'PCI\VEN_1234&DEV_4321', power={'SelectiveSuspend': 'Enabled'},
            advanced=[], dns=[{'AddressFamily': 2, 'ServerAddresses': ['192.168.1.1']}],
            wifi=dict(ssid='Test AP', bssid='00:11:22:33:44:55', channel=36, band='5 GHz',
                      signal_percent=70, nearby=[]))],
        route=dict(InterfaceIndex=18, NextHop='192.168.1.1'), wifi={'interfaces': []})


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'network.sqlite3')


@pytest.mark.parametrize('khz,expected', [
    (2412000, ('2.4 GHz', 1)), (2472000, ('2.4 GHz', 13)), (2484000, ('2.4 GHz', 14)),
    (5180000, ('5 GHz', 36)), (5935000, ('6 GHz', 2)), (5955000, ('6 GHz', 1)),
    (7115000, ('6 GHz', 233)), (0, ('Unknown band', None))])
def test_native_frequency_channels(khz, expected):
    assert frequency_channel(khz) == expected


def test_native_windows_structure_layout():
    # Win32 fixed-width ABI fields, including padding before uint64 timestamps.
    assert ctypes.sizeof(BSS) == 360
    assert BSS.frequency.offset == 92
    assert ctypes.sizeof(Association) == 68


def test_channel_counts_deduplicate_radios_and_keep_bands_separate():
    a = dict(bssid='a', rssi_dbm=-70, band='2.4 GHz', channel=1)
    b = dict(bssid='b', rssi_dbm=-60, band='2.4 GHz', channel=4)
    c = dict(bssid='c', rssi_dbm=-50, band='6 GHz', channel=1)
    out = network.channel_summary({'interfaces': [{'nearby': [a, b, c]},
                                                  {'nearby': [dict(a, rssi_dbm=-40)]}]})
    one = next(r for r in out if r['band'] == '2.4 GHz' and r['channel'] == 1)
    assert one['access_points'] == 1
    assert one['adjacent_24ghz'] == 1
    assert one['strongest_dbm'] == -40
    assert next(r for r in out if r['band'] == '6 GHz')['adjacent_24ghz'] == 0


def test_discovery_isolates_provider_failure(monkeypatch):
    def denied():
        raise PermissionError('Access denied')
    monkeypatch.setattr(network, 'adapter_inventory', denied)
    monkeypatch.setattr(network, 'read_wifi', lambda: {'interfaces': [], 'error': 'Location denied'})
    out = network.discover()
    assert out['adapters'] == []
    assert out['error'] == 'Access denied'
    assert out['wifi']['error'] == 'Location denied'


def test_detection_matches_braced_guids_and_physical_media(snapshot, monkeypatch):
    snapshot['adapters'][0]['guid'] = '{' + GUID.upper() + '}'
    monkeypatch.setattr(network, 'adapter_inventory', lambda: copy.deepcopy(snapshot))
    monkeypatch.setattr(network, 'read_wifi', lambda: {'interfaces': [dict(guid=GUID, signal_percent=75)]})
    out = network.discover()
    assert out['adapters'][0]['wifi']['signal_percent'] == 75
    assert out['adapters'][0]['kind'] == 'Wi-Fi'


def test_approval_and_allowlist_precede_any_command(store, monkeypatch):
    monkeypatch.setattr(network, 'discover', lambda: pytest.fail('No provider call without approval'))
    engine = network.NetworkActions(store)
    with pytest.raises(PermissionError, match='Explicit approval'):
        engine.execute(GUID, 'SelectiveSuspend')
    with pytest.raises(ValueError, match='Unsupported property'):
        engine.execute(GUID, 'RsnRekeyOffload', approved=True)
    with pytest.raises(ValueError):
        engine.execute("'; Restart-NetAdapter", 'SelectiveSuspend', approved=True)


def test_power_action_durable_backup_no_restart_and_restore(snapshot, store, monkeypatch):
    state = copy.deepcopy(snapshot)
    monkeypatch.setattr(network, 'is_admin', lambda: True)
    monkeypatch.setattr(network, 'discover', lambda: copy.deepcopy(state))
    calls = []
    key = f'network:rollback:{GUID}:SelectiveSuspend'
    def mutate(script, timeout):
        backup = Store(store.path).get(key)
        assert backup['previous'] == 'Enabled'
        assert backup['target'] == 'Disabled'
        assert '-NoRestart' in script and 'Restart-NetAdapter' not in script
        assert 'Set-NetAdapterPowerManagement -SelectiveSuspend' in script
        assert '-Name' not in script
        calls.append(script)
        state['adapters'][0]['power']['SelectiveSuspend'] = 'Disabled' if len(calls) == 1 else 'Enabled'
    monkeypatch.setattr(network, 'powershell', mutate)
    engine = network.NetworkActions(store)
    engine.execute(GUID, 'SelectiveSuspend', approved=True)
    assert store.get(key)
    engine.execute(GUID, 'SelectiveSuspend', approved=True, revert=True)
    assert store.get(key) is None
    assert len(calls) == 2
    assert len([r for r in store.runs() if r['kind'] == 'network snapshot']) == 3


def test_failed_mutation_keeps_backup_and_allows_noop_recovery(snapshot, store, monkeypatch):
    monkeypatch.setattr(network, 'is_admin', lambda: True)
    monkeypatch.setattr(network, 'discover', lambda: copy.deepcopy(snapshot))
    def fail(*args):
        raise RuntimeError('Driver rejected request')
    monkeypatch.setattr(network, 'powershell', fail)
    engine = network.NetworkActions(store)
    with pytest.raises(RuntimeError):
        engine.execute(GUID, 'SelectiveSuspend', approved=True)
    key = f'network:rollback:{GUID}:SelectiveSuspend'
    assert store.get(key)['previous'] == 'Enabled'
    assert store.actions()[0]['status'] == 'failed'
    engine.execute(GUID, 'SelectiveSuspend', approved=True, revert=True)
    assert store.get(key) is None


def test_restore_rejects_replaced_adapter(snapshot, store, monkeypatch):
    monkeypatch.setattr(network, 'is_admin', lambda: True)
    monkeypatch.setattr(network, 'discover', lambda: snapshot)
    monkeypatch.setattr(network, 'powershell', lambda *args: pytest.fail('Must not mutate'))
    store.set(f'network:rollback:{GUID}:SelectiveSuspend', dict(pnp_id='different device', previous='Enabled', target='Disabled'))
    with pytest.raises(ValueError, match='changed since apply'):
        network.NetworkActions(store).execute(GUID, 'SelectiveSuspend', approved=True, revert=True)


def test_verification_failure_retains_original(snapshot, store, monkeypatch):
    monkeypatch.setattr(network, 'is_admin', lambda: True)
    monkeypatch.setattr(network, 'discover', lambda: snapshot)
    monkeypatch.setattr(network, 'powershell', lambda *args: None)
    with pytest.raises(RuntimeError, match='verification failed'):
        network.NetworkActions(store).execute(GUID, 'SelectiveSuspend', approved=True)
    assert store.get(f'network:rollback:{GUID}:SelectiveSuspend')['previous'] == 'Enabled'


def test_corrupt_rollback_value_never_reaches_command(snapshot, store, monkeypatch):
    state = copy.deepcopy(snapshot)
    state['adapters'][0]['power']['SelectiveSuspend'] = 'Disabled'
    monkeypatch.setattr(network, 'is_admin', lambda: True)
    monkeypatch.setattr(network, 'discover', lambda: state)
    monkeypatch.setattr(network, 'powershell', lambda *args: pytest.fail('Invalid saved value must not execute'))
    store.set(f'network:rollback:{GUID}:SelectiveSuspend', dict(pnp_id=state['adapters'][0]['pnp_id'],
        previous="Enabled; Restart-NetAdapter", target='Disabled'))
    with pytest.raises(ValueError, match='Saved value is invalid'):
        network.NetworkActions(store).execute(GUID, 'SelectiveSuspend', approved=True, revert=True)


def test_no_gateway_is_unavailable_and_route_changes_reset_samples(snapshot, monkeypatch):
    route = [dict(InterfaceIndex=18, NextHop='192.168.1.1')]
    monkeypatch.setattr(network, 'current_route', lambda: route[0])
    monkeypatch.setattr(network, 'read_wifi', lambda: {'interfaces': []})
    monkeypatch.setattr(network, 'ping', lambda host: 10 if host == '1.1.1.1' else None)
    monitor = network.NetworkMonitor()
    first = monitor.sample(snapshot)
    assert first['gateway']['loss_percent'] == 100
    assert first['external']['sent'] == 1
    route[0] = dict(InterfaceIndex=18, NextHop='0.0.0.0')
    second = monitor.sample(snapshot)
    assert second['gateway']['loss_percent'] is None
    assert second['gateway']['sent'] == 0
    assert second['external']['sent'] == 1
    assert second['path_changed']
    assert not second['process_bandwidth']['supported']


def test_recommendations_do_not_claim_proven_benefits(snapshot):
    snapshot['adapters'][0]['wifi']['signal_percent'] = 30
    cards = network.recommendations(snapshot)
    assert any('placement' in c['title'] for c in cards)
    actions = [c for c in cards if c['action']]
    assert len(actions) == 1
    assert actions[0]['action']['property'] == 'SelectiveSuspend'
    assert all('Theoretical' in c['verification'] for c in cards)


def mock_benchmark(snapshot, monkeypatch):
    monkeypatch.setattr(network, 'discover', lambda: copy.deepcopy(snapshot))
    monkeypatch.setattr(network, 'current_route', lambda: snapshot['route'])
    monkeypatch.setattr(network, 'ping', lambda host: 5.0)
    monkeypatch.setattr(network, 'psjson', lambda *args: [{'ms': 3, 'ok': True}] * 5)
    monkeypatch.setitem(network.BENCH_PARAMETERS, 'probes', 3)
    monkeypatch.setitem(network.BENCH_PARAMETERS, 'interval', 0)
    monkeypatch.setattr(network.NetworkBenchmark, 'transfer', lambda self, d, size: dict(mbps=10, seconds=.1, bytes=size))


def test_benchmark_approval_and_cancelled_results_persist(snapshot, store, monkeypatch):
    mock_benchmark(snapshot, monkeypatch)
    engine = network.NetworkBenchmark(store)
    with pytest.raises(PermissionError):
        engine.run('same AC workload')
    assert not store.runs()
    engine.cancel.set()
    out = engine.run('same AC workload', approved=True)
    assert not out['complete']
    assert 'cancelled' in out['errors']
    assert store.runs()[0]['kind'] == 'network benchmark'


def test_real_results_short_load_is_inconclusive(snapshot, store, monkeypatch):
    mock_benchmark(snapshot, monkeypatch)
    out = network.NetworkBenchmark(store).run('same AC workload', approved=True)
    assert out['complete'] and out['stable_path']
    assert out['results']['download_mbps']['value'] == 10
    assert out['results']['dns_ms']['value'] == 3
    assert out['loaded']['download']['increase_ms'] is None
    assert 'Inconclusive' in out['loaded']['download']['status']
    assert not out['loaded']['download']['saturation_verified']
    assert out['before']['adapters'][0]['power'] == {'SelectiveSuspend': 'Enabled'}


def test_dns_provider_failure_does_not_skip_throughput(snapshot, store, monkeypatch):
    mock_benchmark(snapshot, monkeypatch)
    def fail(*args):
        raise RuntimeError('DNS provider unavailable')
    monkeypatch.setattr(network, 'psjson', fail)
    out = network.NetworkBenchmark(store).run('same AC workload', approved=True)
    assert out['results']['download_mbps']['value'] == 10
    assert out['results']['dns_ms']['value'] is None
    assert out['errors']['dns']
    assert not out['complete']


def test_transfer_failure_and_route_change_saved(snapshot, store, monkeypatch):
    mock_benchmark(snapshot, monkeypatch)
    monkeypatch.setattr(network, 'current_route', lambda: dict(InterfaceIndex=99, NextHop='10.0.0.1'))
    def fail(*args):
        raise TimeoutError('Transfer timed out')
    monkeypatch.setattr(network.NetworkBenchmark, 'transfer', fail)
    out = network.NetworkBenchmark(store).run('same workload', approved=True)
    assert not out['stable_path'] and out['path_changes']
    assert not out['complete']
    assert out['results']['upload_mbps']['value'] is None
    assert set(out['errors']) == {'download', 'upload'}


def saved_run(snapshot, identity, speed):
    return dict(id=identity, payload=dict(parameters=dict(network.BENCH_PARAMETERS), conditions='desk AC no VPN idle',
        context=network.context(snapshot), complete=True, stable_path=True, idle_background_mbps=.1,
        signal_before=70, signal_after=72, results={'download_mbps': network.summarize([speed] * 3)}))


def test_comparison_requires_matched_conditions_and_reports_observation(snapshot):
    a, b = saved_run(snapshot, 1, 100), saved_run(snapshot, 2, 110)
    out = network.compare_network(a, b)
    assert out['comparable']
    assert out['results'][0]['status'] == 'Observed improvement'
    assert 'No verified causal improvement' in out['conclusion']
    b['payload']['conditions'] = 'different location'
    assert not network.compare_network(a, b)['comparable']
    assert network.compare_network(a, a)['results'][0]['status'] == 'Not comparable'


@pytest.mark.parametrize('change', ['signal', 'background', 'driver', 'path', 'identity', 'incomplete'])
def test_comparison_rejects_confounds(snapshot, change):
    a, b = saved_run(snapshot, 1, 100), saved_run(snapshot, 2, 120)
    if change == 'signal': b['payload']['signal_after'] = 20
    if change == 'background': b['payload']['idle_background_mbps'] = 30
    if change == 'driver': b['payload']['context']['driver'] = '2.0'
    if change == 'path': b['payload']['stable_path'] = False
    if change == 'identity': b['payload']['context']['bssid'] = None
    if change == 'incomplete': b['payload']['complete'] = False
    assert not network.compare_network(a, b)['comparable']


def test_driver_verification_uses_exact_ids_and_never_installs(snapshot, monkeypatch):
    def query(script, timeout):
        assert "Type='Driver'" in script
        assert '$ids -contains $_.DriverHardwareID' in script
        assert 'Download(' not in script and 'Install(' not in script
        return dict(candidates=[], hardware_ids=['test'], result_code=2)
    monkeypatch.setattr(network, 'psjson', query)
    out = network.verify_driver_updates(snapshot)
    assert out['installed_driver'] == '1.2.3'
    assert 'does not verify latest' in out['status']


def test_transfer_enforces_byte_limit_without_writing_files(store, monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): return b'x' * 10
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://speed.cloudflare.com/__down?bytes=3'
            assert timeout == 10
            return Response()
    monkeypatch.setattr(network.urllib.request, 'build_opener', lambda *args: Opener())
    with pytest.raises(ValueError, match='byte limit'):
        network.NetworkBenchmark(store).transfer('download', 3)


def test_survey_requires_approval_before_native_calls():
    from optimizer.wlan import scan_wifi
    with pytest.raises(PermissionError, match='Explicit approval'):
        scan_wifi(GUID)


def test_network_gui_population_approval_denial_and_history_isolation(snapshot, tmp_path, monkeypatch):
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from optimizer.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    # Keep this UI test completely offline, including existing startup callbacks.
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    panel = window.network_center
    window.timer.stop(); panel.timer.stop(); panel.scan_timer.stop()
    panel.discovered(snapshot)
    assert panel.adapter.count() == 1
    assert panel.properties.rowCount() == 1
    assert '1.2.3' in panel.adapter_text.text()
    assert panel.metrics['Radio'][0].text() == '70%'
    calls = []
    monkeypatch.setattr(window, 'confirm', lambda *args: False)
    monkeypatch.setattr(window, 'launch', lambda *args, **kwargs: calls.append(args))
    panel.change(dict(guid=GUID, property='SelectiveSuspend'))
    panel.conditions.setText('desk AC idle')
    panel.start_benchmark()
    panel.survey()
    assert calls == []
    assert not window.action_busy and window.benchmark is None
    window.store.save_run('network benchmark', saved_run(snapshot, 1, 10)['payload'])
    window.store.save_run('network snapshot', snapshot)
    window.store.save_run('baseline', {'results': {}})
    window.refresh_history(); panel.refresh_history()
    assert window.before.count() == 1
    assert panel.baseline.count() == 1
    assert panel.saved.count() == 2
    window.nav.setCurrentRow(8)
    window.show(); app.processEvents()
    assert window.stack.currentWidget() is window.network_scroll
    assert panel.tabs.count() == 6
    window.close()
