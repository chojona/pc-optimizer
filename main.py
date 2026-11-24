import multiprocessing
import sys
from pathlib import Path


def main():
    from PySide6.QtWidgets import QApplication
    from optimizer.ui import MainWindow
    app=QApplication(sys.argv)
    app.setApplicationName('PC Optimizer')
    app.setOrganizationName('Local Workstation')
    window=MainWindow()
    size=window.store.get('window_size')
    if size: window.resize(*size)
    window.show()
    return app.exec()


if __name__=='__main__':
    multiprocessing.freeze_support()
    sys.exit(main())
