import os
os.environ['QT_QPA_PLATFORM']='offscreen'

from PySide6.QtWidgets import QApplication
from optimizer.ui import MainWindow


def test_gui_builds_all_pages_without_system_changes(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    window.timer.stop()
    assert window.stack.count()==8
    assert len(window.cards)==18
    assert window.store.actions()==[]
    for i in range(8):
        window.nav.setCurrentRow(i)
        assert window.stack.currentIndex()==i
    window.filter.setCurrentText('Recommended')
    assert len(window.cards)>=5
    window.close()
