import copy
import json
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from optimizer.readable import explain_error, explain_result, readable_label
from optimizer.readable_ui import ResultView


def test_readable_results_preserve_evidence_and_missing_values():
    data = {'cpu': [{'NumberOfCores': 6}], 'pagefile_policy': [
        {'AutomaticManagedPagefile': False}], 'results': {
        'download_mbps': {'value': 0, 'samples': [0, None]}},
        'error': 'Provider refused access', 'notes': 'No causal improvement established.',
        'unknownRawField': 'exact device ID: <ABC>&123', 'empty': []}
    original = copy.deepcopy(data)
    text = explain_result(data)
    assert 'Physical processor cores: 6' in text
    assert 'Windows manages virtual memory automatically: No' in text
    assert 'Download speed (Mbit/s)' in text
    assert 'Value: 0' in text
    assert 'Unavailable (no value reported)' in text
    assert 'Provider refused access' in text
    assert data['notes'] in text
    assert data['unknownRawField'] in text
    assert 'No entries recorded.' in text
    assert data == original


def test_units_status_and_unfamiliar_fields():
    text = explain_result({'Capacity': 16 * 2**30, 'status': 'failed',
                           'futureFieldName': 42, 'saturation_verified': False})
    assert 'Memory capacity: 16.00 GiB' in text
    assert 'Status: Could not complete' in text
    assert 'Future Field Name: 42' in text
    assert 'connection was fully loaded: No' in text
    assert 'variation in response time (ms)' in readable_label('gateway_jitter_ms')
    assert 'probes with no reply (%)' in readable_label('external_loss_percent')
    assert readable_label('cpu_error') == 'Processor (CPU) reading error'
    assert 'Clear the cached website name lookups' in explain_result({'action': 'dns'})


def test_result_view_switches_and_keeps_original_data_on_refresh():
    app = QApplication.instance() or QApplication([])
    viewer = ResultView()
    data = {'AutomaticManagedPagefile': False, 'Capacity': 2**30,
            'errors': {'network': '<adapter unavailable>'}}
    viewer.set_data(data)
    assert 'Windows manages virtual memory automatically: No' in viewer.toPlainText()
    assert '<adapter unavailable>' in viewer.toPlainText()
    viewer.technical.setChecked(True)
    assert json.loads(viewer.toPlainText()) == data
    viewer.set_data({'complete': False})
    assert viewer.technical.isChecked()
    assert json.loads(viewer.toPlainText()) == {'complete': False}
    viewer.technical.setChecked(False)
    assert 'All requested tests completed: No' in viewer.toPlainText()
    viewer.setPlainText('Windows tool output\nNo errors found.')
    assert viewer.toPlainText() == 'Windows tool output\nNo errors found.'
    viewer.close()


def test_error_message_uses_cause_without_python_stack_frames():
    details = 'Traceback (most recent call last):\n  File "worker.py", line 8\nPermissionError: Administrator rights required.'
    text = explain_error(details)
    assert 'Administrator rights required.' in text
    assert 'Traceback' not in text and 'worker.py' not in text
    assert 'No error message was reported.' in explain_error('')
