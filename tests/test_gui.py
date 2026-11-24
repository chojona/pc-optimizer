import json
import os
import time
import unittest
from pathlib import Path
from threading import Event

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from optimizer.ai_ui import SYNTHETIC_AI_RESULTS
from optimizer.network_ui import SYNTHETIC_INTELLIGENCE
from optimizer.ui import MainWindow


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = ROOT / 'data' / 'test-temp-ui'


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
    if hasattr(window, 'network_center'):
        window.network_center.stop()
    if hasattr(window, 'ai_panel'):
        window.ai_panel.stop()
    if hasattr(window, 'ai_optimizer'):
        window.ai_optimizer.stop()
    _wait_jobs(window, app)
    window.store.set('window_size', [window.width(), window.height()])
    window.close()
    app.processEvents()


class GuiModernizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.dir = TEMP_ROOT / f'case-{self.id().split(".")[-1]}-{os.getpid()}-{time.time_ns()}'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.window = MainWindow(self.dir)
        _stop_timers(self.window)

    def tearDown(self):
        _close(self.window, self.app)

    def test_builds_pages_and_keyboard_nav(self):
        self.assertEqual(self.window.stack.count(), 11)
        self.assertEqual(self.window.minimumWidth(), 1280)
        self.assertEqual(self.window.minimumHeight(), 720)
        self.assertGreaterEqual(len(self.window.cards), 5)
        self.assertEqual(self.window.store.actions(), [])
        self.window.nav.setFocus(Qt.FocusReason.TabFocusReason)
        for i in range(11):
            self.window.nav.setCurrentRow(i)
            self.assertEqual(self.window.stack.currentIndex(), i)
        self.assertTrue(self.window.nav.accessibleName())
        names = [self.window.nav.item(i).text() for i in range(self.window.nav.count())]
        self.assertIn('Wi-Fi & Network', names)
        self.assertIn('Local AI advice', names)
        self.assertIn('AI Optimizer', names)
        self.window.filter.setCurrentText('Recommended')
        self.assertGreaterEqual(len(self.window.cards), 5)

    def test_results_use_readable_words_with_original_details_available(self):
        data = {'cpu': [{'NumberOfCores': 8}], 'pagefile_policy': [{'AutomaticManagedPagefile': True}]}
        self.window.hardware_ready(data)
        text = self.window.hardware_text.toPlainText()
        self.assertIn('Physical processor cores: 8', text)
        self.assertIn('Windows manages virtual memory automatically: Yes', text)
        self.window.hardware_text.technical.setChecked(True)
        self.assertEqual(json.loads(self.window.hardware_text.toPlainText()), data)
        self.window.store.action('balanced', 'failed', {'error': 'Verification failed; backup retained'})
        self.window.refresh_activity()
        activity = self.window.activity.toPlainText()
        self.assertIn('Balanced power plan', activity)
        self.assertIn('Could not complete', activity)
        self.assertIn('backup retained', activity)
        self.window.network_center.refresh_history()
        self.window.store.save_run('network snapshot', {'signal_percent': 0, 'notes': 'Signal unavailable from this provider'})
        self.window.network_center.refresh_history()
        self.window.network_center.inspect_saved()
        details = self.window.network_center.history_details.toPlainText()
        self.assertIn('Reported Wi-Fi signal quality (%): 0', details)
        self.assertIn('Signal unavailable from this provider', details)
        self.assertEqual(self.window.store.get('hardware'), data)

    def test_error_dialog_keeps_traceback_in_optional_details(self):
        captured = {}

        class Dialog:
            Icon = __import__('optimizer.ui', fromlist=['QMessageBox']).QMessageBox.Icon

            def __init__(self, icon, title, message, parent):
                captured['message'] = message

            def setDetailedText(self, text):
                captured['details'] = text

            def exec(self):
                pass

        import optimizer.ui as ui
        original = ui.QMessageBox
        ui.QMessageBox = Dialog
        try:
            details = 'Traceback (most recent call last):\n  File "worker.py", line 8\nRuntimeError: Verification failed; backup retained'
            self.window.error(details)
            self.assertIn('backup retained', captured['message'])
            self.assertNotIn('Traceback', captured['message'])
            self.assertEqual(captured['details'], details)
            self.assertEqual(self.window.store.actions()[0]['payload']['error'], details)
        finally:
            ui.QMessageBox = original

    def test_network_intelligence_states_with_fixture_provider(self):
        def analyze(snapshot):
            self.assertIsInstance(snapshot, dict)
            if snapshot.get('rounds') == []:
                return SYNTHETIC_INTELLIGENCE['empty']
            return SYNTHETIC_INTELLIGENCE['ok']

        self.window.network_center.analyze_provider = analyze
        self.window.network_center.run_intelligence({'schema_version': 1, 'rounds': [{'n': 1}]})
        _wait_jobs(self.window, self.app)
        self.assertEqual(self.window.network_center.intelligence_state, 'ok')
        self.assertIn('heuristic', self.window.network_center.intel_details.toPlainText().lower())
        self.window.network_center.cancel_intelligence()
        self.assertEqual(self.window.network_center.intelligence_state, 'canceled')

    def test_absent_ai_and_stale_response_suppression(self):
        started = Event()
        release = Event()

        def slow_recommend(snapshot, network_result=None, *, cancel=None):
            started.set()
            while not release.is_set():
                if cancel is not None and ((callable(cancel) and cancel()) or getattr(cancel, 'is_set', lambda: False)()):
                    return dict(SYNTHETIC_AI_RESULTS['canceled'])
                time.sleep(0.01)
            return dict(SYNTHETIC_AI_RESULTS['ok'])

        self.window.ai_panel.set_provider(slow_recommend)
        self.window.ai_panel.refresh()
        self.assertTrue(started.wait(2))
        first_gen = self.window.requests.current('ai')
        self.window.ai_panel.set_provider(lambda *a, **k: dict(SYNTHETIC_AI_RESULTS['unavailable']))
        self.window.ai_panel.refresh()
        second_gen = self.window.requests.current('ai')
        self.assertNotEqual(first_gen, second_gen)
        release.set()
        _wait_jobs(self.window, self.app)
        body = self.window.ai_panel.suggestions.toPlainText().lower()
        self.assertTrue('unavailable' in body or 'not available' in body or 'no local' in body)

    def test_close_during_work_invalidates_callbacks(self):
        release = Event()

        def slow(_progress):
            release.wait(2)
            return {'cpu': []}

        self.window.launch(slow, self.window.hardware_ready, False, channel='hardware')
        self.window.closing = True
        self.window.requests.invalidate()
        release.set()
        _wait_jobs(self.window, self.app)
        self.assertNotEqual(self.window.store.get('hardware'), {'cpu': []})


def test_gui_builds_all_pages_without_system_changes(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    _stop_timers(window)
    assert window.stack.count() == 11
    assert len(window.cards) == 18
    assert window.store.actions() == []
    for i in range(11):
        window.nav.setCurrentRow(i)
        assert window.stack.currentIndex() == i
    names = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert 'AI Optimizer' in names
    assert 'Wi-Fi & Network' in names
    window.filter.setCurrentText('Recommended')
    assert len(window.cards) >= 5
    _close(window, app)


def test_results_use_readable_words_with_original_details_available(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    _stop_timers(window)
    data = {'cpu': [{'NumberOfCores': 8}], 'pagefile_policy': [{'AutomaticManagedPagefile': True}]}
    window.hardware_ready(data)
    assert 'Physical processor cores: 8' in window.hardware_text.toPlainText()
    assert 'Windows manages virtual memory automatically: Yes' in window.hardware_text.toPlainText()
    window.hardware_text.technical.setChecked(True)
    assert json.loads(window.hardware_text.toPlainText()) == data
    window.store.action('balanced', 'failed', {'error': 'Verification failed; backup retained'})
    window.refresh_activity()
    assert 'Balanced power plan' in window.activity.toPlainText()
    assert 'Could not complete' in window.activity.toPlainText()
    assert 'backup retained' in window.activity.toPlainText()
    window.network_center.refresh_history()
    window.store.save_run('network snapshot', {'signal_percent': 0, 'notes': 'Signal unavailable from this provider'})
    window.network_center.refresh_history()
    window.network_center.inspect_saved()
    assert 'Reported Wi-Fi signal quality (%): 0' in window.network_center.history_details.toPlainText()
    assert 'Signal unavailable from this provider' in window.network_center.history_details.toPlainText()
    assert window.store.get('hardware') == data
    _close(window, app)


def test_error_dialog_keeps_traceback_in_optional_details(tmp_path, monkeypatch):
    app = _app()
    monkeypatch.setattr(QTimer, 'singleShot', lambda *args: None)
    window = MainWindow(tmp_path)
    _stop_timers(window)
    captured = {}

    class Dialog:
        def __init__(self, icon, title, message, parent):
            captured['message'] = message

        def setDetailedText(self, text):
            captured['details'] = text

        def exec(self):
            pass

    from optimizer import ui
    Dialog.Icon = ui.QMessageBox.Icon
    monkeypatch.setattr(ui, 'QMessageBox', Dialog)
    details = 'Traceback (most recent call last):\n  File "worker.py", line 8\nRuntimeError: Verification failed; backup retained'
    window.error(details)
    assert 'backup retained' in captured['message']
    assert 'Traceback' not in captured['message']
    assert captured['details'] == details
    assert window.store.actions()[0]['payload']['error'] == details
    _close(window, app)


if __name__ == '__main__':
    unittest.main()
