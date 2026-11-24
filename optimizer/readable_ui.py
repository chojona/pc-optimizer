"""Shared result viewer with a readable default and lossless technical details."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from .readable import explain_result


# Semantic statuses use both color and text so state never depends on color alone.
STATUS_META = {
    'ok': ('#6ee7c7', 'OK'),
    'loading': ('#66bbff', 'Loading'),
    'empty': ('#a9b9ce', 'Empty'),
    'insufficient': ('#f2b86b', 'Insufficient evidence'),
    'partial': ('#f2b86b', 'Partial result'),
    'error': ('#f07178', 'Error'),
    'canceled': ('#c3a6ff', 'Canceled'),
    'unavailable': ('#a9b9ce', 'Unavailable'),
    'warning': ('#f2b86b', 'Warning'),
    'info': ('#66bbff', 'Info'),
}


class StatusBadge(QWidget):
    """Accessible status chip: visible label plus color accent."""

    def __init__(self, status='unavailable', text=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.swatch = QLabel('●')
        self.swatch.setObjectName('statusSwatch')
        self.caption = QLabel()
        self.caption.setObjectName('statusCaption')
        self.caption.setWordWrap(True)
        layout.addWidget(self.swatch, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.caption, 1)
        self.set_status(status, text)

    def set_status(self, status, text=None):
        color, default = STATUS_META.get(status, STATUS_META['unavailable'])
        label = text or default
        self.swatch.setText('●')
        self.swatch.setStyleSheet(f'color:{color}; font-size:14px;')
        self.caption.setText(label)
        self.setAccessibleName(f'Status: {label}')
        self.setToolTip(label)


class ResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.technical = QCheckBox('Show technical details')
        self.technical.setToolTip('Switch between readable wording and the original diagnostic data.')
        self.technical.setAccessibleName('Show technical details')
        layout.addWidget(self.technical)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setAccessibleName('Result details')
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
        self.text.setStyleSheet(
            'font-family: ' + ('Consolas; font-size:13px;' if technical else '"Segoe UI"; font-size:14px;')
        )
        self.text.setPlainText(content)
