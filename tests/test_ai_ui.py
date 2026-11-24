import contextlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from optimizer.ai import Canceled, RuntimeUnavailable, recommend as real_recommend
from optimizer.ai_ui import (
    CancelToken, RequestGate, SYNTHETIC_AI_RESULTS,
    resolve_recommend, unavailable_result,
)
from optimizer.readable_ui import StatusBadge
from optimizer.ui import MainWindow


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / 'data' / 'test-temp-ai-ui'
AI_FIXTURES = ROOT / 'tests' / 'fixtures' / 'ai'
_MISSING = object()


@contextlib.contextmanager
def backend_module_absent():
    """Simulate a build that never shipped `optimizer.ai`.

    `resolve_recommend` imports the backend lazily and returns None on ImportError.
    Testing that branch used to rely on the package genuinely not existing, which
    stopped being true once it was implemented; a `None` entry in `sys.modules`
    makes the import machinery raise ImportError, so the branch is exercised
    explicitly instead of by accident.
    """
    saved = sys.modules.get('optimizer.ai', _MISSING)
    sys.modules['optimizer.ai'] = None
    try:
        yield
    finally:
        if saved is _MISSING:
            sys.modules.pop('optimizer.ai', None)
        else:
            sys.modules['optimizer.ai'] = saved


def ai_fixture(name):
    return json.loads((AI_FIXTURES / name).read_text(encoding='utf-8'))


def model_response(evidence_key='network.signal_percent'):
    return json.dumps({'schema_version': 1, 'suggestions': [{
        'id': 'wired-trial',
        'title': 'Compare a wired trial from the same location',
        'rationale': 'Reported signal quality is low, which costs retries.',
        'evidence': [evidence_key],
        'risk': 'low',
    }]})


class StubRuntime:
    """Stands in for `optimizer.ai.OllamaRuntime`; never opens a socket."""

    def __init__(self, text=None, error=None, started=None, cancel_aware=False):
        self.text, self.error = text, error
        self.started, self.cancel_aware = started, cancel_aware
        self.prompts = []

    def generate(self, prompt, is_canceled=lambda: False):
        self.prompts.append(prompt)
        if self.started is not None:
            self.started.set()
        if self.cancel_aware:
            for _ in range(500):
                if is_canceled():
                    raise Canceled('canceled while the request was in flight')
                time.sleep(0.01)
        if self.error:
            raise self.error
        return self.text


def backend_provider(runtime):
    """The real backend with a stub runtime injected through its documented seam."""
    def provider(snapshot, network_result=None, *, cancel=None):
        return real_recommend(snapshot, network_result, cancel=cancel, runtime=runtime)
    return provider


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

    def _seed_evidence(self, window):
        """Give the panel a synthetic snapshot so the backend collects real evidence."""
        snapshot = ai_fixture('snapshot.json')
        window.hardware = snapshot['inventory']
        window.network_center.snapshot = snapshot['network']
        window.network_center.intelligence = ai_fixture('network_result.json')['diagnostic']
        return snapshot

    def test_resolve_recommend_absent_without_provider(self):
        with backend_module_absent():
            self.assertIsNone(resolve_recommend(None))
        provider = lambda snapshot, network_result=None, *, cancel=None: SYNTHETIC_AI_RESULTS['ok']
        self.assertIs(resolve_recommend(provider), provider)

    def test_resolve_recommend_uses_the_installed_backend(self):
        """With the package present, the resolver must find the contract entrypoint."""
        self.assertIs(resolve_recommend(None), real_recommend)

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
        """No backend module at all: the panel must say so and stay usable."""
        window = self._window()
        panel = window.ai_panel
        panel.set_provider(None)
        with backend_module_absent():
            panel.refresh()
            _wait_jobs(window, self.app)
        text = panel.suggestions.toPlainText().lower()
        self.assertTrue('not present' in text or 'unavailable' in text or 'no local' in text)
        self.assertIn('unavailable', panel.runtime_badge.accessibleName().lower())
        _close(window, self.app)

    def test_panel_falls_back_when_backend_present_but_runtime_unavailable(self):
        """Backend installed, Ollama not running: deterministic fallback, clearly labelled."""
        runtime = StubRuntime(error=RuntimeUnavailable('no local runtime is listening'))
        window = self._window(ai_provider=backend_provider(runtime))
        self._seed_evidence(window)
        panel = window.ai_panel
        panel.refresh()
        _wait_jobs(window, self.app)
        self.assertIn('unavailable', panel.runtime_badge.accessibleName().lower())
        self.assertIn('deterministic', panel.model_label.text().lower())
        body = panel.suggestions.toPlainText().lower()
        # The deterministic rules ran on the seeded evidence, so advice is still shown.
        self.assertIn('wired trial', body)
        self.assertIn('approval', body)
        self.assertIn('deterministic fallback', body)
        _close(window, self.app)

    def test_panel_renders_validated_suggestions_from_the_real_backend(self):
        """End-to-end: panel snapshot -> recommend() -> validation -> rendered cards."""
        runtime = StubRuntime(text=model_response())
        window = self._window(ai_provider=backend_provider(runtime))
        self._seed_evidence(window)
        panel = window.ai_panel
        panel.refresh()
        _wait_jobs(window, self.app)
        self.assertIn('ok', panel.runtime_badge.accessibleName().lower())
        self.assertIn('local_llm', panel.model_label.text().lower())
        body = panel.suggestions.toPlainText().lower()
        self.assertIn('wired trial', body)
        self.assertIn('approval', body)
        # The backend really ran: the prompt was built from the panel's own snapshot.
        self.assertTrue(runtime.prompts)
        self.assertIn('network.signal_percent', runtime.prompts[0])
        _close(window, self.app)

    def test_panel_never_renders_identifiers_from_the_snapshot(self):
        """The rendered payload includes evidence, so privacy must hold at the UI too."""
        runtime = StubRuntime(text=model_response())
        window = self._window(ai_provider=backend_provider(runtime))
        self._seed_evidence(window)
        panel = window.ai_panel
        panel.refresh()
        _wait_jobs(window, self.app)
        rendered = panel.suggestions.toPlainText() + panel.status.text() + panel.model_label.text()
        for identifier in ('SyntheticNetwork', 'aa:bb:cc:dd:ee:ff', '192.168.10.1',
                           '0f6ea19b', 'pagefile.sys', '381b4222', 'PCI'):
            self.assertNotIn(identifier, rendered)
            self.assertNotIn(identifier, runtime.prompts[0])
        _close(window, self.app)

    def test_panel_cancellation_reaches_the_backend_request(self):
        """The panel's CancelToken must satisfy the contract's cancel protocol."""
        started = Event()
        runtime = StubRuntime(started=started, cancel_aware=True)
        window = self._window(ai_provider=backend_provider(runtime))
        self._seed_evidence(window)
        panel = window.ai_panel
        panel.refresh()
        self.assertTrue(started.wait(5), 'backend request never started')
        panel.cancel()
        _wait_jobs(window, self.app, timeout=10)
        self.assertIn('canceled', panel.runtime_badge.accessibleName().lower())
        self.assertIn('deterministic', panel.model_label.text().lower())
        _close(window, self.app)

    def test_stale_backend_result_is_discarded_when_superseded(self):
        """A superseded generation must never overwrite the newer result."""
        first_started, release_first = Event(), Event()
        calls = []

        def provider(snapshot, network_result=None, *, cancel=None):
            index = len(calls)
            calls.append(index)
            if index == 0:
                first_started.set()
                release_first.wait(5)
                return dict(SYNTHETIC_AI_RESULTS['ok'], detail='STALE FIRST RESULT')
            return dict(SYNTHETIC_AI_RESULTS['ok'], detail='FRESH SECOND RESULT')

        window = self._window(ai_provider=provider)
        panel = window.ai_panel
        panel.refresh()
        self.assertTrue(first_started.wait(5), 'first request never started')
        first_generation = window.requests.current('ai')
        panel.refresh()
        self.assertNotEqual(first_generation, window.requests.current('ai'))
        release_first.set()
        _wait_jobs(window, self.app, timeout=10)
        self.assertEqual(len(calls), 2)
        self.assertIn('fresh second result', panel.status.text().lower())
        self.assertNotIn('stale first', panel.status.text().lower())
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
    with backend_module_absent():
        window.ai_panel.refresh()
        _wait_jobs(window, app)
    text = window.ai_panel.suggestions.toPlainText().lower()
    assert 'advisory' in text or 'unavailable' in text or 'not present' in text
    _close(window, app)


def test_ai_panel_with_empty_snapshot_reports_no_evidence(tmp_path, monkeypatch):
    """Backend present but the window holds no inventory yet: a typed, honest status.

    This is the state the old absent-runtime test actually produced once the backend
    existed. It is `error` ("nothing to explain"), not `unavailable`, and no runtime
    request is made at all — the engine short-circuits before contacting one.
    """
    from PySide6.QtCore import QTimer
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    runtime = StubRuntime(text=model_response())
    window = MainWindow(tmp_path, ai_provider=backend_provider(runtime))
    _stop_timers(window)
    window.ai_panel.refresh()
    _wait_jobs(window, app)
    assert 'error' in window.ai_panel.runtime_badge.accessibleName().lower()
    assert 'no recognized evidence' in window.ai_panel.status.text().lower()
    assert runtime.prompts == [], 'no runtime request may be made without evidence'
    _close(window, app)


if __name__ == '__main__':
    unittest.main()
