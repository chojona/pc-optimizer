import os
import time
import unittest
from pathlib import Path
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from optimizer.ai_optimizer_ui import (
    FIXTURE_BANNER, SYNTHETIC_AGENTS, SYNTHETIC_BENCHMARKS, SYNTHETIC_CATALOG,
    SYNTHETIC_INVENTORY, AiOptimizerCenter, unavailable_agents, unavailable_benchmarks,
    unavailable_catalog, unavailable_inventory,
)
from optimizer.ai_ui import SYNTHETIC_AI_RESULTS
from optimizer.ui import MainWindow


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / 'data' / 'test-temp-ai-optimizer'


def _app():
    return QApplication.instance() or QApplication([])


def _stop_timers(window):
    window.timer.stop()
    window.network_center.timer.stop()
    window.network_center.scan_timer.stop()


def _wait_jobs(window, app, timeout=8):
    deadline = time.time() + timeout
    while window.jobs and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    # Drain queued cross-thread result signals after the last job leaves the set.
    for _ in range(30):
        app.processEvents()
        time.sleep(0.01)


def _close(window, app):
    _stop_timers(window)
    window.closing = True
    window.requests.invalidate()
    window.network_center.stop()
    window.ai_panel.stop()
    window.ai_optimizer.stop()
    _wait_jobs(window, app)
    window.close()
    app.processEvents()


class AiOptimizerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def _window(self, **kwargs):
        from PySide6.QtCore import QTimer
        path = TEMP_ROOT / f'case-{self.id().split(".")[-1]}-{os.getpid()}-{time.time_ns()}'
        path.mkdir(parents=True, exist_ok=True)
        original = QTimer.singleShot
        QTimer.singleShot = staticmethod(lambda *args, **kwargs: None)
        try:
            window = MainWindow(path, **kwargs)
        finally:
            QTimer.singleShot = original
        _stop_timers(window)
        return window

    def test_dashboard_mounted_with_five_sections(self):
        window = self._window()
        dash = window.ai_optimizer
        self.assertIsInstance(dash, AiOptimizerCenter)
        self.assertEqual(dash.tabs.count(), 5)
        titles = [dash.tabs.tabText(i) for i in range(dash.tabs.count())]
        self.assertEqual(
            titles,
            ['Overview', 'Model explorer', 'Model comparison', 'Coding agents', 'Recommendations'],
        )
        names = [window.nav.item(i).text() for i in range(window.nav.count())]
        self.assertIn('AI Optimizer', names)
        self.assertIn('Wi-Fi & Network', names)
        self.assertIn('Overview', names)
        _close(window, self.app)

    def test_unavailable_defaults_without_providers(self):
        window = self._window()
        dash = window.ai_optimizer
        dash.refresh_models()
        dash.refresh_compare()
        dash.refresh_agents()
        dash.refresh_recommend()
        _wait_jobs(window, self.app)
        self.assertIn('unavailable', dash.models_badge.accessibleName().lower())
        self.assertIn('Unavailable', dash.models_table.item(0, 0).text())
        self.assertIn('Unavailable', dash.compare_table.item(0, 0).text())
        self.assertIn('unavailable', dash.agents_table.item(0, 1).text().lower())
        body = dash.recommend_view.toPlainText().lower()
        self.assertTrue('unavailable' in body or 'not present' in body or 'no advisory' in body)
        self.assertNotIn('tokens/s: 120', body)
        _close(window, self.app)

    def test_synthetic_fixtures_are_labeled(self):
        window = self._window()
        dash = window.ai_optimizer
        dash.set_providers(
            inventory_provider=lambda: dict(SYNTHETIC_INVENTORY),
            catalog_provider=lambda: dict(SYNTHETIC_CATALOG),
            benchmark_provider=lambda: dict(SYNTHETIC_BENCHMARKS),
            agent_provider=lambda: dict(SYNTHETIC_AGENTS),
        )
        # Refresh sections sequentially so startup telemetry jobs cannot starve callbacks.
        dash.refresh_models()
        _wait_jobs(window, self.app)
        dash.refresh_compare()
        _wait_jobs(window, self.app)
        dash.refresh_agents()
        _wait_jobs(window, self.app)
        dash.refresh_overview()
        _wait_jobs(window, self.app)
        # Offscreen windows may not be shown; use isHidden() rather than isVisible().
        self.assertFalse(dash.banner.isHidden())
        self.assertIn('Synthetic development fixture', dash.banner.text())
        self.assertIn('fixture', dash.models_badge.accessibleName().lower())
        self.assertEqual(dash.models_table.item(0, 0).text(), 'fixture-local-3b')
        self.assertEqual(dash.compare_table.item(0, 0).text(), 'fixture-local-3b')
        # Comparison metrics stay Unavailable inside the fixture (no fabricated scores).
        self.assertEqual(dash.compare_table.item(0, 1).text(), 'Unavailable')
        self.assertEqual(dash.compare_table.item(0, 2).text(), 'Unavailable')
        agents_text = ' '.join(
            dash.agents_table.item(r, 0).text() for r in range(dash.agents_table.rowCount())
        ).lower()
        self.assertIn('codex', agents_text)
        self.assertIn('cursor', agents_text)
        self.assertIn('claude', agents_text)
        _close(window, self.app)

    def test_recommendations_render_fixture_and_tradeoff_placeholders(self):
        window = self._window(ai_provider=lambda *a, **k: dict(SYNTHETIC_AI_RESULTS['ok']))
        dash = window.ai_optimizer
        dash.recommend_provider = lambda *a, **k: dict(SYNTHETIC_AI_RESULTS['ok'])
        dash.refresh_recommend()
        _wait_jobs(window, self.app)
        body = dash.recommend_view.toPlainText().lower()
        self.assertIn('wired trial', body)
        self.assertIn('unavailable', body)  # best_for_* placeholders
        self.assertIn('approval', body)
        _close(window, self.app)

    def test_stale_catalog_response_dropped(self):
        started = Event()
        release = Event()

        def slow():
            started.set()
            release.wait(3)
            return dict(SYNTHETIC_CATALOG)

        window = self._window()
        dash = window.ai_optimizer
        dash.set_providers(catalog_provider=slow)
        dash.refresh_models()
        self.assertTrue(started.wait(2))
        first = window.requests.current('ai-opt-models')
        dash.set_providers(catalog_provider=lambda: unavailable_catalog('second'))
        dash.refresh_models()
        second = window.requests.current('ai-opt-models')
        self.assertNotEqual(first, second)
        release.set()
        _wait_jobs(window, self.app)
        self.assertEqual(dash.models_table.item(0, 0).text(), 'Unavailable')
        _close(window, self.app)

    def test_cancel_recommendation_request(self):
        started = Event()
        release = Event()

        def slow(snapshot, network_result=None, *, cancel=None):
            started.set()
            for _ in range(300):
                if cancel is not None and ((callable(cancel) and cancel()) or getattr(cancel, 'is_set', lambda: False)()):
                    return dict(SYNTHETIC_AI_RESULTS['canceled'])
                if release.is_set():
                    break
                time.sleep(0.01)
            return dict(SYNTHETIC_AI_RESULTS['ok'])

        window = self._window()
        dash = window.ai_optimizer
        dash.recommend_provider = slow
        dash.refresh_recommend()
        self.assertTrue(started.wait(2))
        dash.cancel_recommend()
        release.set()
        _wait_jobs(window, self.app)
        self.assertIn('cancel', dash.recommend_badge.accessibleName().lower())
        _close(window, self.app)

    def test_close_during_overview_work(self):
        release = Event()

        def slow():
            release.wait(2)
            return dict(SYNTHETIC_INVENTORY)

        window = self._window()
        dash = window.ai_optimizer
        dash.set_providers(inventory_provider=slow)
        dash.refresh_overview()
        dash.stop()
        window.closing = True
        window.requests.invalidate()
        release.set()
        _wait_jobs(window, self.app)
        # Initial unavailable state should not be overwritten after stop/close.
        self.assertFalse(dash.banner.isVisible() and 'Synthetic' in dash.banner.text() and not dash.closed)
        _close(window, self.app)

    def test_helper_envelopes(self):
        self.assertIsNone(unavailable_inventory().get('fixture_kind'))
        self.assertEqual(unavailable_catalog()['models'], [])
        self.assertEqual(unavailable_benchmarks()['comparisons'], [])
        self.assertEqual(len(unavailable_agents()['agents']), 3)


def test_ai_optimizer_page_keeps_network_alive(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    _stop_timers(window)
    assert window.network_center is not None
    assert window.ai_optimizer.tabs.count() == 5
    window.nav.setCurrentRow(window.nav.count() - 1)
    assert window.stack.currentWidget() is window.ai_optimizer_scroll
    window.nav.setCurrentRow(window.nav.count() - 3)  # Wi-Fi & Network is two before last? Overview..Network, Local AI, AI Optimizer
    # Find network by name
    for i in range(window.nav.count()):
        if window.nav.item(i).text() == 'Wi-Fi & Network':
            window.nav.setCurrentRow(i)
            break
    assert window.stack.currentWidget() is window.network_scroll
    _close(window, app)


if __name__ == '__main__':
    unittest.main()
