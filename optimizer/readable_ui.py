"""Shared result viewer with a readable default and lossless technical details."""
import json

from PySide6.QtWidgets import QCheckBox, QTextEdit, QVBoxLayout, QWidget

from .readable import explain_result


class ResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.technical = QCheckBox('Show technical details')
        self.technical.setToolTip('Switch between readable wording and the original diagnostic data.')
        layout.addWidget(self.technical)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.technical.toggled.connect(self.render)
        self.render()

    def set_data(self, data):
        self.data = data
        self.render()

    def setPlainText(self, text):
        self.set_data(text)

    def toPlainText(self):
        return self.text.toPlainText()

    def render(self):
        technical = self.technical.isChecked()
        if technical:
            content = self.data if isinstance(self.data, str) else json.dumps(self.data, indent=2)
        else:
            content = explain_result(self.data)
        self.text.setStyleSheet('font-family: ' + ('Consolas; font-size:13px;' if technical else '"Segoe UI"; font-size:14px;'))
        self.text.setPlainText(content)
