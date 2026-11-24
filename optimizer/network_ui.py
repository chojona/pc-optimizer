"""Network Center composed from the application's existing widgets and worker pool."""
from copy import deepcopy

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QComboBox, QTabWidget, QLineEdit, QScrollArea, QSpinBox, QCheckBox)

from . import network
from .readable import explain_result, readable_label
from .readable_ui import ResultView
from .wlan import scan_wifi


class NetworkCenter(QWidget):
    def __init__(self, host):
        super().__init__()
        # Late import keeps the main window's existing helper API intact.
        from .ui import label, button, table, Chart
        self.label, self.button, self.table = label, button, table
        self.host = host
        self.snapshot = {}
        self.observation = {}
        self.latest_benchmark = None
        try:
            config = network.DiagnosticConfig(**(host.store.get('network:diagnostic_config') or {}))
        except (ValueError, TypeError):
            config = network.DiagnosticConfig()
        self.monitor = network.NetworkMonitor(host.store, config)
        self.setStyleSheet("""
            QTabWidget::pane { border:1px solid #35465f; background:#111c2c; }
            QTabBar::tab { background:#1b2a40; color:#cfdbec; padding:10px 12px;
                          border:1px solid #3b4c66; margin-right:2px; }
            QTabBar::tab:selected { background:#285447; color:#fff; border-bottom:3px solid #75ebc7; }
            QTabBar::tab:hover { background:#304963; color:#fff; }
            QSpinBox { background:#192438; color:#e5efff; padding:6px; border:1px solid #52657e; }
            QLabel#metric { font-size:23px; }
            QLabel#muted { color:#b4c3d8; }
        """)
        self.actions = network.NetworkActions(host.store)
        self.scan_busy = self.sample_busy = self.driver_busy = self.survey_busy = False
        self.closed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('Wi-Fi & Network Center', 'title'))
        layout.addWidget(label('Latency • stability • measured evidence • explicit approval for every setting change', 'muted'))
        row = QHBoxLayout()
        self.adapter = QComboBox()
        self.adapter.setMinimumWidth(280)
        self.adapter.currentIndexChanged.connect(self.show_adapter)
        row.addWidget(label('Inspect adapter:'))
        row.addWidget(self.adapter, 1)
        row.addWidget(button('Refresh / save snapshot', self.refresh))
        layout.addLayout(row)
        self.route_label = label('Detecting IPv4 route to 1.1.1.1…', 'muted')
        layout.addWidget(self.route_label)
        grid = QGridLayout()
        self.metrics = {}
        for i, key in enumerate(('Gateway', 'External', 'Radio', 'Throughput')):
            card = QFrame(); card.setObjectName('card')
            box = QVBoxLayout(card)
            box.addWidget(label(key, 'muted'))
            value, detail = label('Waiting…', 'metric'), label('No samples yet', 'muted')
            box.addWidget(value); box.addWidget(detail)
            self.metrics[key] = value, detail
            grid.addWidget(card, 0, i)
        layout.addLayout(grid)
        charts = QHBoxLayout()
        self.gateway_chart = Chart('Gateway · ICMP ms', '#6ee7c7', None)
        self.external_chart = Chart('External · ICMP ms', '#66bbff', None)
        self.loss_chart = Chart('External · rolling unanswered %', '#f2b86b', 100)
        for chart in (self.gateway_chart, self.external_chart, self.loss_chart):
            chart.setMinimumHeight(95)
            chart.setMaximumHeight(125)
            charts.addWidget(chart)
        layout.addLayout(charts)
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMinimumHeight(430)
        layout.addWidget(self.tabs, 1)
        self.make_recommendations()
        self.make_inspection()
        self.make_channels()
        self.make_benchmarks()
        self.make_history()
        self.make_drivers()
        layout.addWidget(label('Probes use the OS IPv4 route, regardless of inspected adapter. ICMP can be filtered; this is not a game-server or broker execution-latency guarantee. No settings change automatically.', 'muted'))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(2000)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(lambda: self.refresh(save=False))
        self.scan_timer.start(30000)
        QTimer.singleShot(800, lambda: self.refresh(save=False) if not self.closed else None)

    def tab(self, title):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, title)
        return layout

    def make_recommendations(self):
        layout = self.tab('Diagnostics / advice')
        controls = QHBoxLayout()
        self.window_seconds, self.minimum_samples = QSpinBox(), QSpinBox()
        self.window_seconds.setRange(10, 3600)
        self.minimum_samples.setRange(3, 1000)
        self.window_seconds.setValue(self.monitor.config.window_seconds)
        self.minimum_samples.setValue(self.monitor.config.min_samples)
        self.minimum_samples.setToolTip('Spike analysis needs this many prior baseline replies, then this many aligned evaluable rounds. Short windows can remain insufficient.')
        self.probe_targets = QLineEdit(', '.join(self.monitor.config.external_targets))
        self.probe_targets.setToolTip('2-5 distinct IPv4 targets; configuration changes reset evidence')
        controls.addWidget(self.label('Window (s)'))
        controls.addWidget(self.window_seconds)
        controls.addWidget(self.label('Min samples'))
        controls.addWidget(self.minimum_samples)
        controls.addWidget(self.probe_targets, 1)
        controls.addWidget(self.button('Apply measurement config', self.configure_diagnostics))
        layout.addLayout(controls)
        self.diagnostic_status = self.label('Collecting evidence. ICMP nonresponses do not confirm application packet loss.', 'muted')
        layout.addWidget(self.diagnostic_status)
        self.diagnostic_table = self.table(['Target', 'Replies / attempts', 'P50 ms', 'P95 ms', 'P99 ms', 'Max ms', 'Jitter mean |dRTT| ms', 'ICMP unanswered %'])
        self.diagnostic_table.setMinimumHeight(155)
        layout.addWidget(self.diagnostic_table)
        self.diagnostic_details = self.label('Jitter: mean absolute adjacent RTT difference; gaps break pairs. P99 under 100 replies is unstable.', 'muted')
        layout.addWidget(self.diagnostic_details)
        self.area = QScrollArea(); self.area.setWidgetResizable(True)
        self.card_widget = QWidget(); self.card_layout = QVBoxLayout(self.card_widget)
        self.area.setWidget(self.card_widget); layout.addWidget(self.area)
        self.draw_recommendations()

    def make_inspection(self):
        layout = self.tab('Adapter / processes')
        self.adapter_text = self.label('Detecting adapters…', 'muted')
        layout.addWidget(self.adapter_text)
        self.properties = self.table(['Property', 'Configured value', 'Capability / meaning'])
        layout.addWidget(self.properties, 1)
        self.bandwidth = self.table(['Adapter', 'Download Mbit/s', 'Upload Mbit/s'])
        self.bandwidth.setMaximumHeight(160)
        layout.addWidget(self.bandwidth)
        self.process_status = self.label('Per-process bandwidth: unavailable. No ETW byte-accounting provider is integrated. Socket counts and process disk I/O are not bandwidth.', 'muted')
        layout.addWidget(self.process_status)

    def make_channels(self):
        layout = self.tab('Wi-Fi channels')
        layout.addWidget(self.label('OS cached BSS observations • refreshed with live radio queries. Radio surveys require approval because scanning may raise latency. AP counts are a congestion indicator, not airtime utilization. Channel widths / bonded-channel overlap and non-Wi-Fi interference are unavailable.', 'muted'))
        self.survey_button = self.button('Review Wi-Fi radio survey', self.survey)
        layout.addWidget(self.survey_button)
        self.wifi_status = self.label('Waiting for WLAN provider…', 'muted')
        layout.addWidget(self.wifi_status)
        self.channels = self.table(['Band', 'Channel', 'Co-channel APs', 'Adjacent 2.4 GHz APs (20 MHz estimate)', 'Strongest dBm'])
        layout.addWidget(self.channels, 1)
        self.nearby = self.table(['SSID', 'BSSID', 'Band', 'Channel', 'RSSI dBm', 'Quality %', 'Observation UTC'])
        layout.addWidget(self.nearby, 1)

    def make_benchmarks(self):
        layout = self.tab('Benchmarks')
        layout.addWidget(self.label('Bounded HTTPS throughput, configured DNS lookup, idle / loaded ICMP latency, jitter and ICMP nonresponses. Up to 48 MiB download + 12 MiB synthetic upload, plus protocol overhead. Bulk tests can interfere with gaming and trading: run outside critical sessions. Fast links may finish too quickly for useful loaded-latency evidence.', 'muted'))
        self.conditions = QLineEdit()
        self.conditions.setPlaceholderText('Comparison conditions: location, AC/battery, VPN, router, background workload…')
        layout.addWidget(self.conditions)
        row = QHBoxLayout()
        self.run_button = self.button('Review and start benchmark', self.start_benchmark, True)
        self.cancel_button = self.button('Cancel benchmark', self.cancel_benchmark)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.run_button); row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.benchmark_status = self.label('No active network benchmark. Partial and cancelled results are retained.', 'muted')
        layout.addWidget(self.benchmark_status)
        self.bench_table = self.table(['Metric', 'Measured value', 'Interpretation'])
        layout.addWidget(self.bench_table, 1)
        self.bloat_status = self.label('Bufferbloat: not measured yet. No synthetic score or grade.', 'muted')
        layout.addWidget(self.bloat_status)

    def make_history(self):
        layout = self.tab('History / comparison')
        row = QHBoxLayout()
        self.baseline, self.current = QComboBox(), QComboBox()
        row.addWidget(self.label('Before')); row.addWidget(self.baseline, 1)
        row.addWidget(self.label('After')); row.addWidget(self.current, 1)
        row.addWidget(self.button('Compare', self.compare))
        row.addWidget(self.button('Refresh history', self.refresh_history))
        layout.addLayout(row)
        self.compare_status = self.label('Match adapter, driver, route, Wi-Fi channel, signal, DNS, test parameters and declared workload. Internet conditions remain uncontrolled.', 'muted')
        layout.addWidget(self.compare_status)
        self.medium_comparison = QCheckBox('Compare Wi-Fi versus Ethernet (manual connection switch; observational only)')
        layout.addWidget(self.medium_comparison)
        self.compare_table = self.table(['Metric', 'Before', 'After', 'Difference', 'Evidence'])
        layout.addWidget(self.compare_table, 1)
        row = QHBoxLayout()
        self.saved = QComboBox(); row.addWidget(self.saved, 1)
        row.addWidget(self.button('Inspect saved snapshot / result', self.inspect_saved))
        layout.addLayout(row)
        self.history_details = ResultView()
        self.history_details.setMaximumHeight(230)
        layout.addWidget(self.history_details)
        events = QHBoxLayout()
        self.events = QComboBox()
        events.addWidget(self.events, 1)
        events.addWidget(self.button('Inspect diagnostic event', self.inspect_event))
        layout.addLayout(events)
        self.refresh_history()

    def make_drivers(self):
        layout = self.tab('Official drivers')
        layout.addWidget(self.label('Read-only Windows Update search for the routed adapter. Candidates must match its PnP hardware or compatible IDs. No result does not mean the OEM has no newer release. Exact device, OS and OEM release notes still require review. No driver is downloaded or installed.', 'muted'))
        row = QHBoxLayout()
        self.driver_button = self.button('Verify official update candidates', self.verify_drivers, True)
        row.addWidget(self.driver_button)
        for name in ('OEM support', 'Intel support', 'Realtek support'):
            row.addWidget(self.button(name, lambda n=name: self.host.open_url(network.SOURCES[n])))
        layout.addLayout(row)
        self.driver_details = ResultView()
        self.driver_details.setPlainText('Verification has not been requested. Use your system manufacturer for OEM adapters; the ASUS link is for ASUS hardware only.')
        layout.addWidget(self.driver_details, 1)

    def refresh(self, save=True):
        if self.closed or self.scan_busy or self.host.action_busy or self.host.benchmark:
            return
        self.scan_busy = True
        def work(_):
            result = network.discover()
            if save:
                self.host.store.save_run('network snapshot', result)
            return result
        job = self.host.launch(work, self.discovered, False)
        job.signals.done.connect(lambda: setattr(self, 'scan_busy', False))

    def discovered(self, snapshot):
        self.snapshot = snapshot
        old = self.adapter.currentData()
        a = network.active_adapter(snapshot)
        self.adapter.blockSignals(True)
        self.adapter.clear()
        for item in snapshot.get('adapters', []):
            self.adapter.addItem(f"{item['name']} · {item['kind']} · {item['status']}", item['guid'])
        index = self.adapter.findData(old or (a or {}).get('guid'))
        self.adapter.setCurrentIndex(max(0, index))
        self.adapter.blockSignals(False)
        error = snapshot.get('error') or snapshot.get('route_error') or ''
        if 'Access denied' in error:
            error = 'Access denied to Windows CIM inventory; try an administrator session.'
        self.route_label.setText(f"OS IPv4 route → {(a or {}).get('name', 'unavailable')} → gateway {network.gateway(snapshot) or 'unavailable'} → 1.1.1.1. Inventory: {snapshot.get('captured_at')}. " + error[:300])
        self.route_label.setToolTip(error)
        self.show_adapter()
        self.show_wifi(snapshot.get('wifi', {}))
        self.draw_recommendations()
        self.refresh_history()

    def show_adapter(self):
        from .ui import fill, fmt
        a = next((a for a in self.snapshot.get('adapters', []) if a['guid'] == self.adapter.currentData()), None)
        if not a:
            self.adapter_text.setText('Adapter inventory unavailable. See route/provider error above.')
            fill(self.properties, [])
            return
        w = a.get('wifi', {})
        self.adapter_text.setText(f"{a['model']} · {a['kind']} · {a['status']}\nDriver: {a.get('driver') or 'Unavailable'} · link {fmt(a.get('link_bps', 0) / 1e6, ' Mbit/s')} (negotiated, not throughput)\nSSID: {w.get('ssid', 'Unavailable / not Wi-Fi')} · band {w.get('band', 'Unavailable')} · channel {w.get('channel', 'Unavailable')} · {w.get('frequency_khz', 'Unavailable')} kHz · RX {w.get('rx_mbps', 'Unavailable')} / TX {w.get('tx_mbps', 'Unavailable')} Mbit/s\n{a.get('power_error') or ''} {a.get('advanced_error') or ''} {w.get('connection_error') or ''}")
        values = [[readable_label(k), v if v is not None else 'Unavailable', 'Power-management inspection; changes limited to two allowlisted properties'] for k, v in (a.get('power') or {}).items()]
        values += [[p.get('DisplayName') or p.get('RegistryKeyword'), p.get('DisplayValue') or p.get('RegistryValue'),
                    'Read only · supported values: ' + str(p.get('ValidDisplayValues') or p.get('ValidRegistryValues') or 'unavailable')]
                   for p in a.get('advanced', [])]
        fill(self.properties, values)
        self.metrics['Radio'][0].setText(fmt(w.get('signal_percent'), '%', 0) if a['kind'] == 'Wi-Fi' else a['kind'])
        self.metrics['Radio'][1].setText(f"{w.get('ssid', a['name'])} · {w.get('band', 'wired / unavailable')} · channel {w.get('channel', '—')}\nRSSI {w.get('rssi_dbm', 'unavailable')} dBm; cached BSS")

    def show_wifi(self, wifi):
        from .ui import fill
        from datetime import datetime, timezone
        issues = [wifi.get('error', '')] + [w.get('bss_error', '') or w.get('connection_error', '') for w in wifi.get('interfaces', [])]
        self.wifi_status.setText(' · '.join(v for v in issues if v) or wifi.get('source', 'OS cached observations; age depends on WLAN service'))
        fill(self.channels, [[c[k] for k in ('band', 'channel', 'access_points', 'adjacent_24ghz', 'strongest_dbm')]
                              for c in network.channel_summary(wifi)])
        observations = []
        for w in wifi.get('interfaces', []):
            for b in w.get('nearby', []):
                try:
                    observed = datetime.fromtimestamp(b['host_timestamp'] / 1e7 - 11644473600, timezone.utc).isoformat(timespec='seconds')
                except (ValueError, OSError, OverflowError, KeyError):
                    observed = 'Unavailable'
                observations.append([b.get(k) for k in ('ssid', 'bssid', 'band', 'channel', 'rssi_dbm', 'signal_percent')] + [observed])
        fill(self.nearby, observations)

    def survey(self):
        if self.survey_busy or self.host.action_busy or self.host.benchmark:
            return
        a = next((a for a in self.snapshot.get('adapters', []) if a['guid'] == self.adapter.currentData()), {})
        if a.get('kind') != 'Wi-Fi':
            self.wifi_status.setText('Select a detected Wi-Fi adapter to request a survey.')
            return
        if not self.host.confirm('Approve Wi-Fi radio survey',
            'Request a nearby-network scan on ' + a['name'] + '? Scanning can briefly increase latency. '
            'Run outside critical gaming or trading sessions. No network setting will change and no adapter restart or connection switch is requested.'):
            return
        self.survey_busy = True; self.survey_button.setEnabled(False)
        # Reuse the global action interlock to keep bulk benchmarks / transitions out of the survey.
        self.host.action_busy = True
        guid = a['guid']
        def work(_):
            out = scan_wifi(guid, approved=True)
            self.host.store.save_run('network Wi-Fi survey', out)
            return out
        job = self.host.launch(work, self.survey_ready)
        job.signals.done.connect(self.survey_finished)

    def survey_ready(self, wifi):
        self.show_wifi(wifi)
        self.host.status.setText('Wi-Fi survey: ' + wifi.get('survey', {}).get('status', 'Unavailable'))
        self.snapshot['wifi'] = wifi
        for a in self.snapshot.get('adapters', []):
            for w in wifi.get('interfaces', []):
                if network.normalize_guid(a['guid']) == network.normalize_guid(w['guid']):
                    a['wifi'] = w
        self.show_adapter()
        self.draw_recommendations()

    def survey_finished(self):
        self.survey_busy = False; self.survey_button.setEnabled(True)
        self.host.action_busy = False
        self.refresh_history()

    def poll(self):
        if self.closed or self.sample_busy or not self.snapshot:
            return
        self.sample_busy = True
        snapshot = deepcopy(self.snapshot)
        job = self.host.launch(lambda _: self.monitor.sample(snapshot), self.sample_ready, False)
        job.signals.done.connect(lambda: setattr(self, 'sample_busy', False))

    def sample_ready(self, result):
        from .ui import fill, fmt
        self.observation = result
        if result.get('path_changed'):
            for chart in (self.gateway_chart, self.external_chart, self.loss_chart):
                chart.values.clear()
        self.snapshot['route'] = result.get('route')
        self.route_label.setText(f"OS IPv4 route → {result.get('routed_adapter') or 'unavailable / rescan inventory'} → gateway {result['targets']['gateway'] or 'unavailable'} → {', '.join(result['config']['external_targets'])} · updated {result['captured_at']}")
        for key, title in (('gateway', 'Gateway'), ('external', 'External')):
            s = result[key]
            self.metrics[title][0].setText(fmt(s.get('latency_ms'), ' ms'))
            self.metrics[title][1].setText(f"{result['targets'][key] or 'No IPv4 gateway'} · rolling {s['sent']} probes\nJitter {fmt(s.get('jitter_ms'), ' ms')} · unanswered {fmt(s.get('loss_percent'), '%')}")
        d = result['diagnostic']
        self.diagnostic_status.setText(f"{d['fault'].replace('_', ' ').title()} | confidence {d['confidence']} | {d['aligned_rounds']} aligned evaluable rounds | {d['shared_spikes']} shared / {d['external_only_spikes']} external-only spikes")
        fill(self.diagnostic_table, [[t, f"{v['received']} / {v['sent']}", *[fmt(v[k]) for k in
            ('p50_ms', 'p95_ms', 'p99_ms', 'max_ms', 'jitter_ms', 'nonresponse_percent')]]
            for t, v in d['statistics'].items()])
        self.diagnostic_details.setText(d['recommendation'] + '\nAlternatives: ' + '; '.join(d['alternatives']) +
            f"\nSignal quality / gateway RTT Pearson r: {fmt(d['signal']['pearson_r'])} ({d['signal']['pairs']} pairs). Correlation does not establish causation. " +
            'Jitter = mean absolute consecutive RTT difference; gaps break pairs. P99 under 100 replies is unstable. ' +
            f"Provider errors (excluded from ICMP attempts): {sum(v['provider_errors'] for v in d['statistics'].values())}. " + d['limitations'])
        self.gateway_chart.add(result['current'].get('gateway'))
        self.external_chart.add(result['current'].get('external'))
        self.loss_chart.add(result['external'].get('loss_percent'))
        fill(self.bandwidth, [[a['name'], fmt(a['download_bps'] * 8 / 1e6 if a['download_bps'] is not None else None),
                              fmt(a['upload_bps'] * 8 / 1e6 if a['upload_bps'] is not None else None)] for a in result['adapters']])
        routed = next((a for a in result['adapters'] if a['name'] == result.get('routed_adapter')), {})
        self.metrics['Throughput'][0].setText(fmt((routed.get('download_bps') or 0) * 8 / 1e6, ' ↓ Mbit/s') if routed else 'Unavailable')
        self.metrics['Throughput'][1].setText(f"{result.get('routed_adapter') or 'No routed adapter'} · ↑ {fmt((routed.get('upload_bps') or 0) * 8 / 1e6, ' Mbit/s')}\nObserved interface traffic; not a speed test")
        wifi = result.get('wifi', {})
        self.snapshot['wifi'] = wifi
        for a in self.snapshot.get('adapters', []):
            a.pop('wifi', None)
            for w in wifi.get('interfaces', []):
                if network.normalize_guid(a['guid']) == network.normalize_guid(w['guid']):
                    a['wifi'] = w
        self.show_adapter()
        self.show_wifi(wifi)
        self.draw_recommendations()

    def draw_recommendations(self):
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        for r in network.recommendations(self.snapshot, self.observation, self.latest_benchmark):
            card = QFrame(); card.setObjectName('card')
            layout = QVBoxLayout(card)
            layout.addWidget(self.label(r['title'] + '  ·  ' + r['risk'] + ' risk'))
            layout.addWidget(self.label(r['evidence'], 'muted'))
            layout.addWidget(self.label('Expected benefit: ' + r['expected_benefit']))
            layout.addWidget(self.label(r['verification'], 'muted'))
            if r['action']:
                data = r['action']
                layout.addWidget(self.button('Review individual change', lambda d=data: self.change(d)))
            self.card_layout.addWidget(card)
        for backup in self.actions.backups():
            self.card_layout.addWidget(self.button('Restore saved ' + backup['property'] + ' · ' + backup['guid'],
                                                   lambda b=backup: self.change(b, revert=True)))
        self.card_layout.addStretch()

    def change(self, data, revert=False):
        if self.host.action_busy or self.host.benchmark or self.scan_busy:
            self.host.status.setText('Finish active actions, scans or benchmarks before changing network settings.')
            return
        prop = data['property']
        if not self.host.confirm('Approve individual network change',
            f"{'Restore saved' if revert else 'Disable'} {prop} on adapter {data['guid']}?\n\n"
            'Moderate risk: increased power use; useful only for documented power-transition issues. No latency gain is established. '
            'The original value is saved before applying. The adapter will not be restarted. Effective behavior may require a later manual restart. '
            'Configured state is verified; restore refuses to overwrite later changes. Proceed outside critical gaming or trading sessions.'):
            return
        self.host.action_busy = True
        job = self.host.launch(lambda _: self.actions.execute(data['guid'], prop, approved=True, revert=revert), self.action_ready)
        job.signals.done.connect(self.action_finished)

    def action_ready(self, out):
        self.host.status.setText(out)

    def action_finished(self):
        self.host.action_busy = False
        self.draw_recommendations()
        self.refresh(save=False)
        self.host.refresh_activity()

    def start_benchmark(self):
        if self.host.benchmark or self.host.action_busy or self.scan_busy:
            self.benchmark_status.setText('Finish the active benchmark, scan or action first.')
            return
        conditions = self.conditions.text().strip()
        if not conditions:
            self.benchmark_status.setText('Enter comparison conditions before starting.')
            self.conditions.setFocus()
            return
        if not self.host.confirm('Approve external benchmark traffic',
            'Send up to 48 MiB of download and 12 MiB of synthetic upload data to speed.cloudflare.com over HTTPS, '
            'query www.microsoft.com through your configured DNS resolver and probe your gateway / 1.1.1.1? '
            'Cloudflare sees your public IP. Tests may use metered data and create congestion affecting games, calls and trading. '
            'Close competing workloads, use the same VPN and power source, and run outside critical sessions. No network setting will change.'):
            return
        engine = network.NetworkBenchmark(self.host.store)
        self.host.benchmark = engine
        self.run_button.setEnabled(False); self.cancel_button.setEnabled(True)
        self.benchmark_status.setText('Benchmark starting…')
        job = self.host.launch(lambda progress: engine.run(conditions, progress, approved=True), self.benchmark_ready)
        job.signals.progress.connect(self.benchmark_status.setText)
        job.signals.done.connect(self.benchmark_finished)

    def cancel_benchmark(self):
        if isinstance(self.host.benchmark, network.NetworkBenchmark):
            self.host.benchmark.cancel.set()
            self.benchmark_status.setText('Cancelling after the current bounded I/O operation…')

    def benchmark_ready(self, out):
        from .ui import fill, fmt
        self.latest_benchmark = out
        fill(self.bench_table, [[readable_label(k), fmt(v['value']), 'Single-stream throughput' if k.endswith('_mbps') else
                                ('Website name lookup through the configured resolver; cache may contribute' if k.startswith('dns_') else 'Response-time probe; routing/filtering may affect results')]
                               for k, v in out['results'].items()])
        self.benchmark_status.setText(f"Saved run #{out['id']} · " + ('Completed' if out['complete'] else 'Some tests did not complete.\n' + explain_result(out['errors'])))
        self.bloat_status.setText('Bufferbloat / loaded latency:\n' + '\n'.join(
            f"{k}: {fmt(v.get('increase_ms'), ' ms increase')} · {v['status']}" for k, v in out['loaded'].items()) +
            '\nNo grade: bottleneck saturation and causality are unverified.')
        self.refresh_history()
        self.draw_recommendations()

    def benchmark_finished(self):
        self.host.benchmark = None
        self.run_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.refresh(save=False)

    def refresh_history(self):
        runs = [r for r in self.host.store.runs() if r['kind'].startswith('network ')]
        for widget in (self.saved, self.baseline, self.current):
            previous = widget.currentData()
            widget.clear()
            choices = runs if widget is self.saved else [r for r in reversed(runs) if r['kind'] == 'network benchmark']
            for r in choices:
                widget.addItem(f"#{r['id']} · {r['created']} · {r['kind']}", r['id'])
            index = widget.findData(previous)
            widget.setCurrentIndex(index if index >= 0 else (widget.count() - 1 if widget is self.current else 0))

        if hasattr(self, 'events'):
            previous = self.events.currentData()
            self.events.clear()
            for event in self.host.store.diagnostic_events():
                self.events.addItem(f"#{event['id']} | {event['created']} | {event['payload']['diagnostic']['fault']}", event['id'])
            self.events.setCurrentIndex(max(0, self.events.findData(previous)))

    def inspect_event(self):
        event = next((e for e in self.host.store.diagnostic_events() if e['id'] == self.events.currentData()), None)
        self.history_details.set_data(event if event else 'No diagnostic events saved yet.')

    def configure_diagnostics(self):
        if self.sample_busy:
            self.diagnostic_status.setText('Wait for the active probe round before applying configuration.')
            return
        try:
            config = network.DiagnosticConfig(window_seconds=self.window_seconds.value(),
                min_samples=self.minimum_samples.value(),
                external_targets=tuple(t.strip() for t in self.probe_targets.text().split(',')))
            self.monitor.configure(config)
            self.observation = {}
            for chart in (self.gateway_chart, self.external_chart, self.loss_chart):
                chart.values.clear()
            self.diagnostic_status.setText('Configuration saved. Evidence window reset; collecting fresh samples.')
        except ValueError as exc:
            self.diagnostic_status.setText(str(exc))

    def inspect_saved(self):
        r = next((r for r in self.host.store.runs() if r['id'] == self.saved.currentData()), None)
        self.history_details.set_data(r if r else 'No saved selection.')

    def compare(self):
        from .ui import fill, fmt
        runs = {r['id']: r for r in self.host.store.runs() if r['kind'] == 'network benchmark'}
        a, b = runs.get(self.baseline.currentData()), runs.get(self.current.currentData())
        if not a or not b:
            self.compare_status.setText('Save two network benchmarks before comparing.')
            return
        result = network.compare_network(a, b, medium_comparison=self.medium_comparison.isChecked())
        self.compare_status.setText(('Comparable recorded conditions. ' if result['comparable'] else 'Not comparable: ' + '; '.join(result['reasons']) + '. ') + result['conclusion'])
        fill(self.compare_table, [[readable_label(v['metric']), fmt(v['before']), fmt(v['after']), fmt(v['delta']), v['status']] for v in result['results']])

    def verify_drivers(self):
        if self.driver_busy or self.host.benchmark or self.host.action_busy or not network.active_adapter(self.snapshot):
            return
        self.driver_busy = True; self.driver_button.setEnabled(False)
        self.driver_details.setPlainText('Checking official Windows Update metadata. This can take several minutes…')
        snapshot = deepcopy(self.snapshot)
        def work(_):
            out = network.verify_driver_updates(snapshot)
            self.host.store.save_run('network driver verification', out)
            return out
        job = self.host.launch(work, self.driver_details.set_data)
        job.signals.done.connect(self.driver_finished)

    def driver_finished(self):
        self.driver_busy = False; self.driver_button.setEnabled(True)
        self.refresh_history()

    def stop(self):
        self.closed = True
        self.timer.stop(); self.scan_timer.stop()
