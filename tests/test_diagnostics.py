"""Deterministic offline evidence tests: no network traffic or system changes."""
import pytest

from optimizer.diagnostics import DiagnosticConfig, analyze, latency_stats
from optimizer import network
from optimizer.store import Store

CONFIG = DiagnosticConfig(min_samples=5)
TARGETS = ('gateway', *CONFIG.external_targets)


def rounds(count=40, pattern=None, skew=0):
    out = []
    for i in range(count):
        values = dict.fromkeys(TARGETS, 10.)
        if pattern:
            pattern(i, values)
        out.append(dict(at=i * 2, captured_at=f'round-{i}', signal_at=i * 2,
            signal_percent=80 - i,
            probes={t: dict(ms=v, start=i * 2 + (skew if t != 'gateway' else 0),
                            end=i * 2 + .1, error=None) for t, v in values.items()}))
    return out


def shared(i, values):
    if i in (10, 20, 30):
        values.update(dict.fromkeys(TARGETS, 100.))


def external(i, values):
    if i in (10, 20, 30):
        values.update(dict.fromkeys(CONFIG.external_targets, 100.))


def test_percentiles_and_jitter_do_not_bridge_nonresponses():
    s = latency_stats([1., 3., None, 100., 104.], minimum=4)
    assert (s['p50_ms'], s['p95_ms'], s['p99_ms'], s['max_ms']) == (3, 104, 104, 104)
    assert s['jitter_ms'] == 3 and s['jitter_pairs'] == 2
    assert s['jitter_p95_ms'] == 4
    assert s['nonresponse_percent'] == 20
    assert s['application_packet_loss'] is None
    assert s['sufficient']
    assert latency_stats([])['p99_ms'] is None
    assert latency_stats([None, None])['jitter_ms'] is None


@pytest.mark.parametrize('pattern,fault', [(shared, 'shared_path_suspected'),
    (external, 'beyond_gateway_suspected'), (None, 'no_repeated_spikes')])
def test_fault_isolation(pattern, fault):
    d = analyze(rounds(pattern=pattern), CONFIG)
    assert d['fault'] == fault
    assert d['aligned_rounds'] == 35
    assert d['alternatives'] and 'not a probability' in d['limitations']
    assert d['confidence'] != 'high'


def test_conflicting_evidence_stays_low_confidence():
    def mixed(i, values):
        shared(i, values)
        if i in (12, 22, 32):
            values.update(dict.fromkeys(CONFIG.external_targets, 100.))
    d = analyze(rounds(pattern=mixed), CONFIG)
    assert d['fault'] == 'conflicting_evidence'
    assert d['shared_spikes'] == d['external_only_spikes'] == 3
    assert d['confidence'] == 'low'


def test_spikes_must_be_aligned_and_multi_target():
    assert analyze(rounds(pattern=shared, skew=.3), CONFIG)['fault'] == 'insufficient_evidence'
    def single(i, values):
        if i in (10, 20, 30):
            values[CONFIG.external_targets[0]] = 100.
    d = analyze(rounds(pattern=single), CONFIG)
    assert d['fault'] == 'target_specific'
    assert d['external_only_spikes'] == 0


def test_insufficient_samples_never_imply_healthy_path():
    d = analyze(rounds(4), CONFIG)
    assert d['fault'] == 'insufficient_evidence'
    assert d['confidence'] == 'insufficient'
    assert not d['statistics']['gateway']['sufficient']
    assert d['signal']['pearson_r'] is None


def test_icmp_packet_loss_is_only_nonresponse_evidence():
    def loss(i, values):
        if i % 2:
            values['gateway'] = None
    d = analyze(rounds(pattern=loss), CONFIG)
    assert d['fault'] == 'icmp_nonresponses'
    assert d['nonresponses']['gateway'] == 50
    assert d['statistics']['gateway']['application_packet_loss'] is None
    assert 'does not confirm' in d['recommendation']


def test_provider_errors_excluded_from_nonresponse_and_break_jitter():
    rows = rounds(3)
    rows[0]['probes']['gateway']['ms'] = 1
    rows[1]['probes']['gateway'].update(ms=None, error='provider unavailable')
    rows[2]['probes']['gateway']['ms'] = 100
    s = analyze(rows, CONFIG)['statistics']['gateway']
    assert s['sent'] == 2 and s['provider_errors'] == 1
    assert s['nonresponse_percent'] == 0
    assert s['jitter_pairs'] == 0


def test_signal_correlation_requires_variation_and_recent_pairs():
    rows = rounds()
    for i, row in enumerate(rows):
        row['probes']['gateway']['ms'] = float(i)
    assert analyze(rows, CONFIG)['signal']['pearson_r'] == pytest.approx(-1)
    for row in rows:
        row['signal_percent'] = 50
    assert analyze(rows, CONFIG)['signal']['pearson_r'] is None
    for row in rows:
        row['signal_at'] -= 10
    assert analyze(rows, CONFIG)['signal']['pairs'] == 0


@pytest.mark.parametrize('kwargs', [dict(window_seconds=1), dict(min_samples=1),
    dict(external_targets=('1.1.1.1',)), dict(external_targets=('1.1.1.1', '1.1.1.1')),
    dict(external_targets=('host.invalid', '8.8.8.8')), dict(alignment_seconds=0)])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        DiagnosticConfig(**kwargs)


def test_monitor_rolling_window_events_and_midround_handover(tmp_path, monkeypatch):
    route = dict(InterfaceIndex=1, NextHop='192.168.1.1')
    clock = [100.]
    monkeypatch.setattr(network.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(network, 'current_route', lambda: dict(route))
    monkeypatch.setattr(network, 'read_wifi', lambda: {'interfaces': []})
    monkeypatch.setattr(network, 'ping', lambda _: 5.)
    store = Store(tmp_path / 'diagnostics.sqlite3')
    m = network.NetworkMonitor(store, DiagnosticConfig(window_seconds=10, min_samples=3))
    one = m.sample({})
    clock[0] += 2
    two = m.sample({})
    assert two['gateway']['sent'] == 2
    assert len(store.diagnostic_events()) == 1  # recurring events throttled
    clock[0] += 20
    assert m.sample({})['gateway']['sent'] == 1
    assert Store(store.path).diagnostic_events()[0]['payload']['rounds']
    def handover(_):
        route['InterfaceIndex'] = 2
        return 5.
    monkeypatch.setattr(network, 'ping', handover)
    changed = m.sample({})
    assert not changed['stable_round'] and changed['gateway']['sent'] == 0
    m.configure(CONFIG)
    assert not m.rounds
    assert store.get('network:diagnostic_config')['min_samples'] == 5


def benchmark(identity, kind):
    wifi = kind == 'Wi-Fi'
    return dict(id=identity, payload=dict(parameters={'protocol': 1}, conditions='same desk AC idle router',
        complete=True, stable_path=True, idle_background_mbps=.1,
        signal_before=70 if wifi else None, signal_after=72 if wifi else None,
        context=dict(kind=kind, guid=f'adapter-{identity}', pnp_id=f'pnp-{identity}', driver='1.0',
                     dns=['192.168.1.1'], ssid='test' if wifi else None,
                     bssid='test' if wifi else None, channel=36 if wifi else None, band='5 GHz' if wifi else None),
        results={'download_mbps': network.summarize([100., 101., 99.])}))


def test_wifi_ethernet_comparison_allows_different_adapters_but_explains_confounds():
    wifi, wired = benchmark(1, 'Wi-Fi'), benchmark(2, 'Ethernet')
    assert not network.compare_network(wifi, wired)['comparable']
    d = network.compare_network(wifi, wired, medium_comparison=True)
    assert d['comparable'] and 'confounds' in d['conclusion']
    assert network.compare_network(wired, wifi, medium_comparison=True)['comparable']
    wired['payload']['conditions'] = 'different router'
    assert not network.compare_network(wifi, wired, medium_comparison=True)['comparable']


def test_no_blanket_driver_update_recommendation():
    snapshot = dict(route={'InterfaceIndex': 1}, adapters=[dict(index=1, name='test', driver='old', model='test')])
    assert not any('driver' in c['title'].lower() for c in network.recommendations(snapshot))

def test_diagnostic_gui_population_config_and_event_history(tmp_path, monkeypatch):
    import os
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from optimizer.ui import MainWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    monkeypatch.setattr(network, 'read_wifi', lambda: {'interfaces': []})
    monkeypatch.setattr(network, 'current_route', lambda: dict(InterfaceIndex=1, NextHop='192.168.1.1'))
    monkeypatch.setattr(network, 'ping', lambda _: 5.)
    window = MainWindow(tmp_path)
    panel = window.network_center
    window.timer.stop(); panel.timer.stop(); panel.scan_timer.stop()
    result = panel.monitor.sample({})
    result['diagnostic'] = analyze(rounds(pattern=shared), CONFIG)
    panel.sample_ready(result)
    assert panel.diagnostic_table.rowCount() == 4
    assert 'Shared Path Suspected' in panel.diagnostic_status.text()
    assert 'Correlation does not establish causation' in panel.diagnostic_details.text()
    panel.refresh_history()
    assert panel.events.count() == 1
    panel.inspect_event()
    assert 'application_packet_loss' in panel.history_details.toPlainText()
    panel.window_seconds.setValue(240)
    panel.minimum_samples.setValue(10)
    panel.configure_diagnostics()
    assert panel.monitor.config.window_seconds == 240
    assert window.store.get('network:diagnostic_config')['min_samples'] == 10
    assert not panel.monitor.rounds
    panel.probe_targets.setText('invalid')
    panel.configure_diagnostics()
    assert panel.monitor.config.window_seconds == 240
    assert 'distinct' in panel.diagnostic_status.text()
    assert panel.medium_comparison.isCheckable()
    assert panel.tabs.usesScrollButtons()
    window.close()
