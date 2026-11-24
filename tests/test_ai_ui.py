import os
import time
import unittest
from pathlib import Path
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from optimizer.ai_ui import (
    CancelToken, RequestGate, SYNTHETIC_AI_RESULTS,
    resolve_recommend, unavailable_result,
)
from optimizer.readable_ui import StatusBadge
from optimizer.ui import MainWindow


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / 'data' / 'test-temp-ai-ui'


def _app():
    return QApplication.instance() or QApplication([])


def _stop_timers(window):
    window.timer.stop()
    window.network_center.timer.stop()
    window.network_center.scan_timer.stop()


def _wait_jobs(window, app, timeout=5):
    deadline = time.time() + timeout
    while window.jobs and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def _close(window, app):
    _stop_timers(window)
    window.closing = True
    window.requests.invalidate()
    window.network_center.stop()
    window.ai_panel.stop()
    _wait_jobs(window, app)
    window.close()
    app.processEvents()


class AiUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def _window(self, **kwargs):
        path = TEMP_ROOT / f'case-{self.id().split(".")[-1]}-{os.getpid()}-{time.time_ns()}'
        path.mkdir(parents=True, exist_ok=True)
        window = MainWindow(path, **kwargs)
        _stop_timers(window)
        return window

    def test_resolve_recommend_absent_without_provider(self):
        self.assertIsNone(resolve_recommend(None))
        provider = lambda snapshot, network_result=None, *, cancel=None: SYNTHETIC_AI_RESULTS['ok']
        self.assertIs(resolve_recommend(provider), provider)

    def test_status_badge_exposes_text_not_color_alone(self):
        badge = StatusBadge('error', 'Advisory status: error')
        self.assertIn('error', badge.accessibleName().lower())
        self.assertIn('error', badge.caption.text().lower())

    def test_cancel_token_protocol(self):
        token = CancelToken()
        self.assertFalse(token.is_set())
        self.assertFalse(token())
        token.cancel()
        self.assertTrue(token.is_set())
        self.assertTrue(token())

    def test_request_gate_drops_stale_generations(self):
        gate = RequestGate()
        first = gate.next('ai')
        second = gate.next('ai')
        self.assertTrue(gate.accept('ai', second))
        self.assertFalse(gate.accept('ai', first))
        gate.invalidate('ai')
        self.assertFalse(gate.accept('ai', second))

    def test_panel_unavailable_without_runtime(self):
        window = self._window()
        panel = window.ai_panel
        panel.set_provider(None)
        panel.refresh()
        _wait_jobs(window, self.app)
        text = panel.suggestions.toPlainText().lower()
        self.assertTrue('not present' in text or 'unavailable' in text or 'no local' in text)
        self.assertIn('unavailable', panel.runtime_badge.accessibleName().lower())
        _close(window, self.app)

    def test_panel_renders_fixture_ok_and_requires_approval(self):
        window = self._window(ai_provider=lambda *a, **k: dict(SYNTHETIC_AI_RESULTS['ok']))
        window.ai_panel.refresh()
        _wait_jobs(window, self.app)
        body = window.ai_panel.suggestions.toPlainText().lower()
        self.assertIn('wired trial', body)
        self.assertIn('approval', body)
        _close(window, self.app)

    def test_repeated_clicks_and_cancel(self):
        started = Event()
        release = Event()

        def slow(snapshot, network_result=None, *, cancel=None):
            started.set()
            for _ in range(200):
                if cancel is not None and ((callable(cancel) and cancel()) or getattr(cancel, 'is_set', lambda: False)()):
                    return dict(SYNTHETIC_AI_RESULTS['canceled'])
                if release.is_set():
                    break
                time.sleep(0.01)
            return dict(SYNTHETIC_AI_RESULTS['ok'])

        window = self._window(ai_provider=slow)
        window.ai_panel.refresh()
        self.assertTrue(started.wait(2))
        first = window.requests.current('ai')
        window.ai_panel.refresh()  # supersedes in-flight request
        self.assertNotEqual(first, window.requests.current('ai'))
        self.assertTrue(window.ai_panel.busy)
        window.ai_panel.cancel()
        release.set()
        _wait_jobs(window, self.app)
        _close(window, self.app)

    def test_unavailable_result_helper(self):
        result = unavailable_result('custom')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['detail'], 'custom')
        self.assertEqual(result['source'], 'deterministic')


def test_ai_panel_absent_runtime_pytest(tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    _stop_timers(window)
    assert window.ai_panel.runtime_badge.caption.text()
    window.ai_panel.refresh()
    _wait_jobs(window, app)
    text = window.ai_panel.suggestions.toPlainText().lower()
    assert 'advisory' in text or 'unavailable' in text or 'not present' in text
    _close(window, app)


if __name__ == '__main__':
    unittest.main()
