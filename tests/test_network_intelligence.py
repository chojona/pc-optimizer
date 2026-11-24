"""Synthetic, offline v1 contract and engine regressions; unittest and pytest."""
import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from optimizer.diagnostics import DiagnosticConfig, analyze as legacy_analyze
from optimizer.network_intelligence import analyze, from_event


def snapshot(pattern='normal', count=40):
    start = datetime(2026, 11, 24, 23, tzinfo=timezone.utc)
    config = DiagnosticConfig(min_samples=5)
    targets = ['gateway', *config.external_targets]
    rows = []
    for i in range(count):
        values = dict.fromkeys(targets, 10.)
        if pattern in ('shared', 'mixed') and i in (10, 20, 30):
            values = dict.fromkeys(targets, 100.)
        if pattern == 'external' and i in (10, 20, 30) or pattern == 'mixed' and i in (12, 22, 32):
            values.update(dict.fromkeys(config.external_targets, 100.))
        if pattern == 'gateway' and i in (10, 20, 30):
            values['gateway'] = 100.
        if pattern == 'single' and i in (10, 20, 30):
            values[config.external_targets[0]] = 100.
        if pattern == 'nonresponse' and i % 2:
            values['gateway'] = None
        at = 100. + 2 * i
        rows.append(dict(captured_at=(start + timedelta(seconds=2*i)).isoformat(), at=at,
                         signal_percent=80. - i, signal_at=at,
                         probes={t: dict(start=at, end=at+.1, ms=v, error=None) for t, v in values.items()}))
    captured = (start + timedelta(seconds=max(0, 2*(count-1)))).isoformat()
    cfg = config.payload()
    cfg['external_targets'] = list(cfg['external_targets'])
    return dict(schema_version=1, captured_at=captured, as_of=captured,
                stable_path=True, config=cfg, rounds=rows)


def ids(result):
    return [f['id'] for f in result['findings']]


class NetworkIntelligenceTests(unittest.TestCase):
    def test_shared_consumer_fixtures(self):
        source = Path(__file__).resolve().parents[1] / 'docs/network-intelligence/examples.json'
        for example in json.loads(source.read_text(encoding='utf-8')):
            with self.subTest(name=example['name']):
                result = analyze(example['snapshot'])
                self.assertEqual(result['summary']['state'], example['expected_state'])
                self.assertIn(example['expected_finding'], ids(result))

    def test_patterns_reuse_legacy_statistics_and_preserve_inputs(self):
        for pattern, fault in [('normal', 'no_repeated_spikes'), ('shared', 'shared_path_suspected'),
                               ('external', 'beyond_gateway_suspected'), ('mixed', 'conflicting_evidence'),
                               ('gateway', 'gateway_icmp_only'), ('single', 'target_specific')]:
            with self.subTest(pattern=pattern):
                source = snapshot(pattern)
                original = copy.deepcopy(source)
                result = analyze(source)
                self.assertEqual(source, original)
                self.assertEqual(result['summary']['state'], 'ok')
                self.assertIn('network.' + fault, ids(result))
                self.assertEqual(result['evidence']['diagnostic'],
                                 legacy_analyze(source['rounds'], DiagnosticConfig(**source['config'])))
                self.assertEqual(result, analyze(source))
                self.assertEqual(result, json.loads(json.dumps(result, allow_nan=False)))
                for record in result['findings'] + result['recommendations']:
                    for ref in record['evidence_refs']:
                        value = result
                        for key in ref.split('/')[1:]:
                            value = value[key.replace('~1', '/').replace('~0', '~')]
                self.assertEqual(len(ids(result)), len(set(ids(result))))
                self.assertTrue(all(r['requires_approval'] is True for r in result['recommendations']))

    def test_sparse_empty_missing_and_misaligned_are_insufficient(self):
        for count in (0, 1, 4, 9):
            self.assertEqual(analyze(snapshot(count=count))['summary']['state'], 'insufficient')
        source = snapshot('shared')
        for row in source['rounds']:
            for key, probe in row['probes'].items():
                if key != 'gateway':
                    probe['start'] += .3
                    probe['end'] += .3
        self.assertEqual(analyze(source)['summary']['state'], 'insufficient')
        source = snapshot()
        for row in source['rounds']:
            del row['probes']['gateway']
        result = analyze(source)
        self.assertIn('network.missing_probes', ids(result))
        self.assertIsNone(result['evidence']['diagnostic']['statistics']['gateway']['latency_ms'])
        self.assertEqual(result['summary']['state'], 'insufficient')

    def test_nonresponse_is_not_application_loss_or_provider_failure(self):
        result = analyze(snapshot('nonresponse'))
        self.assertIn('network.icmp_nonresponses', ids(result))
        stats = result['evidence']['diagnostic']['statistics']['gateway']
        self.assertEqual(stats['nonresponse_percent'], 50)
        self.assertIsNone(stats['application_packet_loss'])
        source = snapshot()
        for row in source['rounds']:
            row['probes']['gateway'].update(ms=None, error='synthetic unavailable')
        result = analyze(source)
        self.assertIn('network.provider_errors', ids(result))
        self.assertNotIn('network.icmp_nonresponses', ids(result))
        stats = result['evidence']['diagnostic']['statistics']['gateway']
        self.assertEqual(stats['provider_errors'], 40)
        self.assertEqual(stats['sent'], 0)
        self.assertIsNone(stats['nonresponse_percent'])

    def test_error_gaps_break_jitter_and_do_not_create_spikes(self):
        source = snapshot(count=3)
        rows = source['rounds']
        rows[0]['probes']['gateway']['ms'] = 1.
        rows[1]['probes']['gateway'].update(ms=None, error='unavailable')
        rows[2]['probes']['gateway']['ms'] = 100.
        st = analyze(source)['evidence']['diagnostic']['statistics']['gateway']
        self.assertEqual(st['jitter_pairs'], 0)
        self.assertEqual(st['nonresponse_percent'], 0)

    def test_mixed_evidence_and_confidence_never_imply_causality(self):
        result = analyze(snapshot('mixed'))
        finding = next(f for f in result['findings'] if f['id'] == 'network.conflicting_evidence')
        self.assertEqual(finding['confidence'], 'low')
        self.assertIn('Mixed evidence', finding['explanation'])
        self.assertIn('not measured probabilities', ' '.join(result['limitations']))

    def test_stale_filtering_uses_supplied_clock_including_boundary(self):
        source = snapshot('shared')
        captured = datetime.fromisoformat(source['captured_at'])
        source['as_of'] = (captured + timedelta(seconds=120)).isoformat()
        result = analyze(source)
        self.assertEqual(result['evidence']['analyzed_rounds'], 1)
        self.assertEqual(result['evidence']['stale_rounds'], 39)
        self.assertEqual(result['summary']['state'], 'insufficient')
        source['as_of'] = (captured + timedelta(seconds=121)).isoformat()
        result = analyze(source)
        self.assertEqual(result['evidence']['analyzed_rounds'], 0)
        self.assertIn('network.stale_data', ids(result))
        self.assertNotIn('network.shared_path_suspected', ids(result))

    def test_route_change_suppresses_inference(self):
        source = snapshot('shared')
        source['stable_path'] = False
        result = analyze(source)
        self.assertEqual(result['summary']['state'], 'insufficient')
        self.assertIsNone(result['evidence']['diagnostic'])
        self.assertIn('network.unstable_path', ids(result))
        self.assertNotIn('network.shared_path_suspected', ids(result))

    def test_wifi_correlation_requires_recent_variable_signal(self):
        source = snapshot()
        for i, row in enumerate(source['rounds']):
            row['probes']['gateway']['ms'] = float(i)
        result = analyze(source)
        self.assertIn('network.wifi_signal_correlation', ids(result))
        self.assertAlmostEqual(result['evidence']['diagnostic']['signal']['pearson_r'], -1)
        for row in source['rounds']:
            row['signal_at'] -= 10
        result = analyze(source)
        self.assertEqual(result['evidence']['diagnostic']['signal']['pairs'], 0)
        self.assertIn('network.wifi_signal_unavailable', ids(result))
        for row in source['rounds']:
            row['signal_at'] = row['at']
            row['signal_percent'] = 50
        self.assertIn('network.wifi_signal_unavailable', ids(analyze(source)))

    def test_strict_top_level_and_config_validation(self):
        for key, bad in [('schema_version', 2), ('schema_version', True), ('stable_path', 1),
                         ('as_of', '2026-11-24T23:00:00'), ('as_of', 'not a date'),
                         ('as_of', '2026-11-24T23:00:00+01:00'), ('as_of', '2026-01-01T00:00:00Z'),
                         ('rounds', {}), ('config', None), ('unknown', 1)]:
            with self.subTest(key=key, bad=bad):
                source = snapshot()
                source[key] = bad
                with self.assertRaises(ValueError):
                    analyze(source)
        for key, bad in [('min_samples', True), ('min_samples', 2), ('window_seconds', 3601),
                         ('min_spikes', 0), ('min_spikes', 1001), ('alignment_seconds', 0),
                         ('alignment_seconds', 2), ('spike_floor_ms', 0),
                         ('external_targets', ['::1', '8.8.8.8']),
                         ('external_targets', ['1.1.1.1', '1.1.1.1']),
                         ('external_targets', ['host.invalid', '8.8.8.8']),
                         ('external_targets', ('1.1.1.1', '8.8.8.8'))]:
            with self.subTest(key=key, bad=bad):
                source = snapshot()
                source['config'][key] = bad
                with self.assertRaises(ValueError):
                    analyze(source)
        for key in snapshot():
            source = snapshot()
            del source[key]
            with self.assertRaises(ValueError):
                analyze(source)

    def test_round_probe_and_timestamp_validation(self):
        mutations = [
            lambda s: s['rounds'][0].update(at=-1),
            lambda s: s['rounds'][1].update(at=100.),
            lambda s: s['rounds'][1].update(captured_at='2026-11-24T23:01:10Z'),
            lambda s: s['rounds'][0].update(captured_at='2026-12-01T00:00:00Z'),
            lambda s: s['rounds'][0].update(signal_percent=101),
            lambda s: s['rounds'][0].pop('signal_at'),
            lambda s: s['rounds'][0]['probes'].update(unknown={}),
            lambda s: s['rounds'][0]['probes']['gateway'].update(ms=-1),
            lambda s: s['rounds'][0]['probes']['gateway'].update(ms=60001),
            lambda s: s['rounds'][0]['probes']['gateway'].update(start=99),
            lambda s: s['rounds'][0]['probes']['gateway'].update(end=99),
            lambda s: s['rounds'][0]['probes']['gateway'].update(ms=None, error=''),
            lambda s: s['rounds'][0]['probes']['gateway'].update(error='contradictory success'),
        ]
        for mutate in mutations:
            source = snapshot()
            mutate(source)
            with self.assertRaises(ValueError):
                analyze(source)

    def test_bounds_precede_statistical_work(self):
        cases = [snapshot(count=257), None, {'schema_version': float('nan')},
                 {'key': float('inf')}, {'key': 10**10000}, {'key': object()},
                 {1: 'value'}, {'key': '\ud800'}, {'key': 'x'*1025}, {'key': [None]*16385}]
        cyclic = {}; cyclic['self'] = cyclic
        cases.append(cyclic)
        oversized = snapshot(count=100)
        for row in oversized['rounds']:
            for probe in row['probes'].values():
                probe.update(ms=None, error='\u20ac'*1024)
        cases.append(oversized)
        node_limit = {'x': [{str(i): None for i in range(100)} for _ in range(100)]}
        cases.append(node_limit)
        with patch('optimizer.network_intelligence.analyze_diagnostics') as legacy:
            for value in cases:
                with self.assertRaises(ValueError):
                    analyze(value)
            legacy.assert_not_called()

    def test_event_adapter_ignores_precomputed_claims_and_copies(self):
        source = snapshot('shared')
        event = dict(captured_at=source['captured_at'], rounds=source['rounds'],
                     config=DiagnosticConfig(min_samples=5).payload(), stable_round=True,
                     diagnostic={'fault': 'untrusted invented diagnosis'}, path=['synthetic'])
        projected = from_event(event, as_of=source['as_of'])
        self.assertEqual(projected, source)
        self.assertIn('network.shared_path_suspected', ids(analyze(projected)))
        projected['rounds'][0]['probes']['gateway']['ms'] = 999
        self.assertEqual(event['rounds'][0]['probes']['gateway']['ms'], 10.)
        for bad in (None, {}, dict(event, stable_round=None), dict(event, rounds=source['rounds']*10)):
            with self.assertRaises(ValueError):
                from_event(bad, as_of=source['as_of'])

    def test_no_probes_storage_or_host_commands(self):
        # Import/reload and analysis must work even when all likely I/O rails fail.
        source = snapshot('shared')
        with patch.object(socket, 'socket', side_effect=AssertionError('socket')), \
             patch.object(subprocess, 'run', side_effect=AssertionError('command')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process')), \
             patch('builtins.open', side_effect=AssertionError('file')), \
             patch.object(Path, 'open', side_effect=AssertionError('path')):
            module = importlib.reload(sys.modules['optimizer.network_intelligence'])
            self.assertEqual(module.analyze(source)['summary']['state'], 'ok')

    def test_import_does_not_require_gui_or_network_backend(self):
        code = '''
import sys
sys.modules['PySide6'] = None
sys.modules['psutil'] = None
sys.modules['optimizer.network'] = None
sys.modules['optimizer.windows'] = None
sys.modules['optimizer.wlan'] = None
sys.modules['optimizer.store'] = None
sys.modules['optimizer.ai'] = None
from optimizer.network_intelligence import analyze
assert callable(analyze)
'''
        completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == '__main__':
    unittest.main()
