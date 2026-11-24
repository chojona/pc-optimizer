import os
import json
os.environ['QT_QPA_PLATFORM']='offscreen'

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from optimizer.ui import MainWindow


def test_gui_builds_all_pages_without_system_changes(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(QTimer,'singleShot',lambda *args:None)
    window=MainWindow(tmp_path)
    window.timer.stop()
    window.network_center.timer.stop()
    window.network_center.scan_timer.stop()
    assert window.stack.count()==9
    assert len(window.cards)==18
    assert window.store.actions()==[]
    for i in range(9):
        window.nav.setCurrentRow(i)
        assert window.stack.currentIndex()==i
    window.filter.setCurrentText('Recommended')
    assert len(window.cards)>=5
    window.close()


def test_results_use_readable_words_with_original_details_available(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(QTimer,'singleShot',lambda *args:None)
    window=MainWindow(tmp_path)
    window.timer.stop()
    window.network_center.timer.stop()
    window.network_center.scan_timer.stop()
    data={'cpu':[{'NumberOfCores':8}],'pagefile_policy':[{'AutomaticManagedPagefile':True}]}
    window.hardware_ready(data)
    assert 'Physical processor cores: 8' in window.hardware_text.toPlainText()
    assert 'Windows manages virtual memory automatically: Yes' in window.hardware_text.toPlainText()
    window.hardware_text.technical.setChecked(True)
    assert json.loads(window.hardware_text.toPlainText())==data
    window.store.action('balanced','failed',{'error':'Verification failed; backup retained'})
    window.refresh_activity()
    assert 'Balanced power plan' in window.activity.toPlainText()
    assert 'Could not complete' in window.activity.toPlainText()
    assert 'backup retained' in window.activity.toPlainText()
    window.network_center.refresh_history()
    window.store.save_run('network snapshot',{'signal_percent':0,'notes':'Signal unavailable from this provider'})
    window.network_center.refresh_history()
    window.network_center.inspect_saved()
    assert 'Reported Wi-Fi signal quality (%): 0' in window.network_center.history_details.toPlainText()
    assert 'Signal unavailable from this provider' in window.network_center.history_details.toPlainText()
    assert window.store.get('hardware')==data
    window.close()


def test_error_dialog_keeps_traceback_in_optional_details(tmp_path, monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(QTimer,'singleShot',lambda *args:None)
    window=MainWindow(tmp_path)
    window.timer.stop()
    window.network_center.timer.stop()
    window.network_center.scan_timer.stop()
    captured={}
    class Dialog:
        def __init__(self, icon, title, message, parent):
            captured['message']=message
        def setDetailedText(self, text):
            captured['details']=text
        def exec(self):
            pass
    from optimizer import ui
    Dialog.Icon=ui.QMessageBox.Icon
    monkeypatch.setattr(ui,'QMessageBox',Dialog)
    details='Traceback (most recent call last):\n  File "worker.py", line 8\nRuntimeError: Verification failed; backup retained'
    window.error(details)
    assert 'backup retained' in captured['message']
    assert 'Traceback' not in captured['message']
    assert captured['details']==details
    assert window.store.actions()[0]['payload']['error']==details
    window.close()
