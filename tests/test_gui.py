import os
os.environ['QT_QPA_PLATFORM']='offscreen'

from PySide6.QtWidgets import QApplication
from optimizer.ui import MainWindow


def test_gui_builds_all_pages_without_system_changes(tmp_path):
    app=QApplication.instance() or QApplication([])
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
