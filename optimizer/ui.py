import ctypes
import json
import os
import statistics
import sys
import traceback
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QInputDialog, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget)

from . import __version__, stability
from .actions import (ActionEngine, startup_entries, startup_change, disabled_startups,
                      terminate_process, BALANCED, HIGH)
from .benchmarks import BenchmarkEngine, TESTS, PARAMETERS, compare_runs, import_presentmon, fingerprint
from .store import Store, timestamp
from .ai_ui import AiAdvisorPanel, RequestGate
from .readable import explain_error, explain_result, readable_label
from .readable_ui import ResultView, StatusBadge
from .telemetry import Telemetry, process_list, publisher
from .windows import (OFFICIAL, inventory, driver_inventory, update_search,
                      stability as event_scan, firmware_url, is_admin, guid, run)

ROOT=Path(__file__).resolve().parent.parent

STYLE='''
QWidget {background:#0d1320; color:#dbe5f4; font-family:"Segoe UI"; font-size:14px; selection-background-color:#285b70; selection-color:#ffffff;}
QMainWindow {background:#0d1320;}
QFrame#card {background:#161f30; border:1px solid #28354a; border-radius:12px;}
QFrame#card QLabel, QFrame#card QCheckBox {background:transparent;}
QWidget#sidebar {background:#101827; border-right:1px solid #28354a;}
QWidget#sidebar QLabel {background:transparent;}
QLabel#brand {font-size:20px; font-weight:700; color:#f4f8ff; letter-spacing:0.4px;}
QLabel#title {font-size:26px; font-weight:700; color:#f4f8ff;}
QLabel#muted {color:#a9b9ce; font-size:13px;}
QLabel#section {font-size:15px; font-weight:600; color:#f4f8ff;}
QLabel#metric {font-size:28px; font-weight:600; color:#6ee7c7;}
QLabel#metricCompact {font-size:22px; font-weight:600; color:#6ee7c7;}
QLabel#statusCaption {font-size:13px; font-weight:600; color:#dbe5f4;}
QLabel#statusSwatch {font-size:14px;}
QListWidget {background:#101827; border:none; padding:0; font-size:14px; outline:none;}
QListWidget::item {padding:12px 10px; border-radius:7px; margin:3px 0;}
QListWidget::item:hover {background:#19283b;}
QListWidget::item:selected {background:#203950; color:#80f0d2;}
QListWidget::item:focus {border:1px solid #6ee7c7;}
QPushButton {background:#22334a; border:1px solid #3a4c64; border-radius:6px; padding:9px 15px;}
QPushButton:hover {background:#304761;}
QPushButton:pressed {background:#19283b;}
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QTextEdit:focus, QTableWidget:focus, QListWidget:focus, QCheckBox:focus, QSpinBox:focus, QTabBar::tab:focus {border:2px solid #6ee7c7;}
QPushButton:disabled {color:#8998ac; background:#182233; border-color:#29364b;}
QPushButton#primary {background:#237b6a; color:#fff; border-color:#329d87; font-weight:600;}
QPushButton#primary:hover {background:#29927d;}
QPushButton#danger {background:#713642; border-color:#9c4e5b;}
QComboBox,QLineEdit {background:#192438; border:1px solid #35455c; border-radius:6px; padding:8px; min-height:20px;}
QComboBox {padding-right:28px;}
QSpinBox {background:#192438; color:#dbe5f4; padding:6px; border:1px solid #52657e; border-radius:6px;}
QComboBox::drop-down {subcontrol-origin:padding; subcontrol-position:top right; width:26px; border:none; border-left:1px solid #35455c;}
QComboBox::down-arrow {image:url("@ASSETS@/chevron-down.svg"); width:12px; height:12px;}
QComboBox QAbstractItemView {background:#192438; color:#dbe5f4; border:1px solid #465b76; padding:4px; selection-background-color:#285b70; selection-color:white; outline:none;}
QTextEdit {background:#101827; border:1px solid #2d3b51; border-radius:6px; padding:10px; font-family:Consolas; font-size:13px;}
QTableWidget {background:#121b2a; alternate-background-color:#172236; border:1px solid #2c3b51; border-radius:6px; gridline-color:#263349;}
QTableWidget::item {padding:6px 8px; border:none;}
QTableWidget::item:selected {background:#24465a; color:#ffffff;}
QHeaderView {font-size:13px; font-weight:600;}
QHeaderView::section {background:#202e43; color:#c5d3e5; padding:10px 8px; border:none; border-bottom:1px solid #35455c;}
QTableCornerButton::section {background:#202e43; border:none;}
QTabWidget::pane {background:#101827; border:1px solid #2c3b51; border-radius:8px; top:-1px;}
QTabBar {background:transparent; font-size:13px; font-weight:600;}
QTabBar::tab {background:#162235; color:#b8c7db; border:1px solid #2c3b51; border-bottom:3px solid #2c3b51; border-top-left-radius:6px; border-top-right-radius:6px; padding:11px 12px; margin-right:4px;}
QTabBar::tab:hover {background:#22364d; color:#f4f8ff;}
QTabBar::tab:selected {background:#20394a; color:#99f6df; border-bottom:3px solid #6ee7c7;}
QTabBar::tab:focus {border-top-color:#6ee7c7;}
QTabBar QToolButton {background:#22334a; color:#f4f8ff; border:1px solid #465b76; border-radius:4px;}
QProgressBar {border:1px solid #34465f; border-radius:5px; text-align:center; background:#172235; min-height:15px;}
QProgressBar::chunk {background:#309a86; border-radius:4px;}
QScrollArea {border:none;}
QScrollBar:vertical {background:#101827; width:12px; margin:0;}
QScrollBar:horizontal {background:#101827; height:12px; margin:0;}
QScrollBar::handle:vertical {background:#40536d; border-radius:5px; min-height:32px; margin:2px;}
QScrollBar::handle:horizontal {background:#40536d; border-radius:5px; min-width:32px; margin:2px;}
QScrollBar::handle:hover {background:#607895;}
QScrollBar::add-line, QScrollBar::sub-line {width:0; height:0;}
QScrollBar::add-page, QScrollBar::sub-page {background:transparent;}
QCheckBox {spacing:8px; padding:4px;}
QCheckBox::indicator {width:16px; height:16px; border:1px solid #71849e; border-radius:4px; background:#101827;}
QCheckBox::indicator:checked {image:url("@ASSETS@/check.svg"); background:#237b6a; border-color:#80f0d2;}
QCheckBox::indicator:disabled {border-color:#35455c;}
QToolTip {background:#24334b; color:white; border:1px solid #50627d;}
'''.replace('@ASSETS@',(ROOT/'optimizer'/'assets').as_posix())


def configure_theme(app):
    # Fusion respects the dark palette for native arrows, checks and dialogs.
    app.setStyle('Fusion')
    palette=QPalette()
    for role,color in {
        'Window':'#0d1320', 'WindowText':'#dbe5f4', 'Base':'#101827',
        'AlternateBase':'#172236', 'Text':'#dbe5f4', 'Button':'#22334a',
        'ButtonText':'#dbe5f4', 'Highlight':'#285b70', 'HighlightedText':'#ffffff',
        'ToolTipBase':'#24334b', 'ToolTipText':'#ffffff', 'PlaceholderText':'#a9b9ce',
        'Light':'#607895', 'Midlight':'#40536d', 'Mid':'#35455c',
        'Dark':'#101827', 'Shadow':'#080e18', 'Link':'#80f0d2',
    }.items():
        palette.setColor(getattr(QPalette.ColorRole,role),QColor(color))
    for role in (QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText,QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled,role,QColor('#8998ac'))
    app.setPalette(palette)


class Signals(QObject):
    result=Signal(object)
    error=Signal(str)
    progress=Signal(str)
    done=Signal()


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.setAutoDelete(False)
        self.signals=Signals()
        self.function=function

    def run(self):
        try:
            value=self.function(self.signals.progress.emit)
            try:
                self.signals.result.emit(value)
            except RuntimeError:
                return
        except Exception:
            try:
                self.signals.error.emit(traceback.format_exc())
            except RuntimeError:
                return
        finally:
            try:
                self.signals.done.emit()
            except RuntimeError:
                pass


def label(text, kind=None):
    w=QLabel(text)
    w.setWordWrap(True)
    if kind: w.setObjectName(kind)
    return w


def button(text, fn, primary=False):
    w=QPushButton(text)
    w.clicked.connect(lambda checked=False:fn())
    if primary: w.setObjectName('primary')
    return w


def table(headers):
    w=QTableWidget(0,len(headers))
    w.setHorizontalHeaderLabels(headers)
    for i,header in enumerate(headers): w.horizontalHeaderItem(i).setToolTip(header)
    w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    w.setAlternatingRowColors(True)
    w.setShowGrid(False)
    w.verticalHeader().setDefaultSectionSize(40)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    w.horizontalHeader().setStretchLastSection(True)
    w.verticalHeader().hide()
    return w


def fill(w, data):
    w.setSortingEnabled(False)
    w.setRowCount(len(data))
    for i,row in enumerate(data):
        for j,value in enumerate(row):
            item=QTableWidgetItem(str(value if value is not None else 'Unavailable'))
            item.setToolTip(item.text())
            w.setItem(i,j,item)
    w.resizeColumnsToContents()
    for col in range(w.columnCount()): w.setColumnWidth(col,min(420,w.columnWidth(col)))


def fmt(value, suffix='', digits=1):
    return 'Unavailable' if value is None else f'{value:,.{digits}f}{suffix}'


class Chart(QWidget):
    def __init__(self, title, color='#6ee7c7', maximum=100):
        super().__init__()
        self.title,self.color,self.maximum=title,QColor(color),maximum
        self.values=deque(maxlen=90)
        self.setMinimumHeight(150)
        self.setToolTip('Hover to inspect a recorded sample. Live charts retain the latest 90 samples.')
        self.setMouseTracking(True)

    def add(self,value):
        self.values.append(float(value) if value is not None else None)
        self.update()

    def mouseMoveEvent(self,event):
        if self.values:
            i=min(len(self.values)-1,max(0,round((event.position().x()-12)/max(1,self.width()-24)*(len(self.values)-1))))
            self.setToolTip(f'{self.title} · sample {i+1}: {fmt(self.values[i])}')

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#161f30'))
        p.setPen(QColor('#a9b9ce'))
        p.drawText(14,23,p.fontMetrics().elidedText(self.title,Qt.TextElideMode.ElideRight,max(40,self.width()-28)))
        top,bottom=38,self.height()-20
        p.setPen(QPen(QColor('#29364b'),1))
        for n in range(4):
            y=top+(bottom-top)*n/3
            p.drawLine(12,int(y),self.width()-12,int(y))
        good=[v for v in self.values if v is not None]
        if not good: return
        maximum=self.maximum or max(max(good)*1.1,1)
        path=QPainterPath()
        connected=False
        for i,value in enumerate(self.values):
            if value is None:
                connected=False
                continue
            x=12+(self.width()-24)*i/max(1,len(self.values)-1)
            y=bottom-min(1,max(0,value/maximum))*(bottom-top)
            if not connected: path.moveTo(x,y)
            else: path.lineTo(x,y)
            connected=True
        p.setPen(QPen(self.color,2))
        p.drawPath(path)
        p.drawText(self.width()-130,self.height()-4,fmt(self.values[-1]))


class MainWindow(QMainWindow):
    def __init__(self, data_dir=None, ai_provider=None, analyze_provider=None):
        super().__init__()
        self.setWindowTitle('PC Optimizer · Local workstation control')
        self.resize(1440,900)
        # Acceptance target: usable at 1280×720 and common display scaling.
        self.setMinimumSize(1280,720)
        self.setStyleSheet(STYLE)
        self.store=Store(Path(data_dir or ROOT/'data')/'optimizer.sqlite3')
        stability.import_evidence(self.store)
        self.engine=ActionEngine(self.store)
        self.pool=QThreadPool(self)
        self.pool.setMaxThreadCount(6)
        self.jobs=set()
        self.closing=False
        self.requests=RequestGate(self)
        self.hardware=self.store.get('hardware',{})
        self.telemetry=Telemetry()
        self.telemetry_busy=False
        self.action_busy=False
        self.benchmark=None
        self.processes=[]
        self.startups=[]
        self.drivers=[]
        self.updates=[]
        self.cards=[]
        self.ai_provider=ai_provider
        self.analyze_provider=analyze_provider
        shell=QWidget()
        self.setCentralWidget(shell)
        outer=QHBoxLayout(shell)
        outer.setContentsMargins(0,0,0,0)
        left=QWidget()
        left.setObjectName('sidebar')
        left.setFixedWidth(236)
        side=QVBoxLayout(left)
        side.setContentsMargins(16,24,16,20)
        side.setSpacing(12)
        side.addWidget(label('PC OPTIMIZER','brand'))
        side.addWidget(label('LOCAL WORKSTATION','muted'))
        self.nav=QListWidget()
        self.nav.setAccessibleName('Primary navigation')
        self.nav.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        pages=['Overview','Optimization Center','Driver Manager','Benchmark Center','Before & After','Startup & Processes','Stability Center','Activity & Settings']
        self.nav.addItems(pages)
        for index,name in enumerate(pages):
            item=self.nav.item(index)
            item.setToolTip(name)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f'Navigate to {name}')
        side.addWidget(self.nav)
        side.addWidget(label('Real telemetry.\nMeasured changes.\nYour files stay yours.','muted'))
        self.privilege=label('Administrator session' if is_admin() else 'Standard user session','muted')
        side.addWidget(self.privilege)
        outer.addWidget(left)
        right=QVBoxLayout()
        right.setContentsMargins(22,14,22,14)
        right.setSpacing(10)
        self.stack=QStackedWidget()
        self.stack.setAccessibleName('Main content pages')
        right.addWidget(self.stack,1)
        self.status=label('Starting live monitoring…','muted')
        self.status.setAccessibleName('Application status')
        self.progress=QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet('QProgressBar {min-height:4px; border:0; border-radius:3px;}')
        self.progress.setRange(0,1)
        self.progress.setValue(0)
        right.addWidget(self.progress)
        right.addWidget(self.status)
        outer.addLayout(right,1)
        self.make_dashboard()
        self.make_optimizations()
        self.make_drivers()
        self.make_benchmarks()
        self.make_compare()
        self.make_processes()
        self.make_stability()
        self.make_activity()
        from .network_ui import NetworkCenter
        self.network_center=NetworkCenter(self, analyze_provider=analyze_provider)
        self.network_scroll=QScrollArea()
        self.network_scroll.setWidgetResizable(True)
        self.network_scroll.setWidget(self.network_center)
        self.stack.addWidget(self.network_scroll)
        self.nav.addItem('Wi-Fi & Network')
        self.nav.item(self.nav.count()-1).setData(Qt.ItemDataRole.AccessibleTextRole,'Navigate to Wi-Fi and Network')
        self.ai_panel=AiAdvisorPanel(self, provider=ai_provider)
        self.stack.addWidget(self.ai_panel)
        self.nav.addItem('Local AI advice')
        self.nav.item(self.nav.count()-1).setData(Qt.ItemDataRole.AccessibleTextRole,'Navigate to Local AI advice')
        from .ai_optimizer_ui import AiOptimizerCenter
        self.ai_optimizer=AiOptimizerCenter(self, recommend_provider=ai_provider)
        self.ai_optimizer_scroll=QScrollArea()
        self.ai_optimizer_scroll.setWidgetResizable(True)
        self.ai_optimizer_scroll.setWidget(self.ai_optimizer)
        self.stack.addWidget(self.ai_optimizer_scroll)
        self.nav.addItem('AI Optimizer')
        self.nav.item(self.nav.count()-1).setData(Qt.ItemDataRole.AccessibleTextRole,'Navigate to AI Optimizer')
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        for widget in self.findChildren(QTableWidget):
            widget.ensurePolished()
            widget.resizeColumnsToContents()
        self.timer=QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1800)
        QTimer.singleShot(100,self.poll)
        QTimer.singleShot(300,self.scan_hardware)

    def page(self,title,subtitle):
        w=QWidget()
        layout=QVBoxLayout(w)
        layout.setContentsMargins(0,0,0,0)
        layout.setSpacing(14)
        layout.addWidget(label(title,'title'))
        layout.addWidget(label(subtitle,'muted'))
        self.stack.addWidget(w)
        return layout

    def launch(self,fn,callback=None,progress=True,channel=None,start=True):
        """Schedule work on the shared pool.

        When start=False, the caller must connect any extra result/done handlers
        and then call pool.start(job). Connecting after pool.start can miss
        instantaneous worker emissions (QueuedConnection has nothing to deliver
        to if no slot was connected yet).
        """
        job=Job(fn)
        self.jobs.add(job)
        if progress:
            self.progress.setRange(0,0)
            job.signals.progress.connect(self.status.setText)
        if callback:
            if channel:
                generation=self.requests.next(channel)
                def guarded(result, expected=generation, name=channel):
                    if self.closing or not self.requests.accept(name, expected):
                        return
                    try:
                        callback(result)
                    except RuntimeError:
                        # Widget tree may already be torn down during close.
                        return
                job.signals.result.connect(guarded)
            else:
                def guarded(result):
                    if self.closing:
                        return
                    try:
                        callback(result)
                    except RuntimeError:
                        return
                job.signals.result.connect(guarded)
        job.signals.error.connect(self.error)
        job.signals.done.connect(lambda:self.job_done(job))
        if start:
            self.pool.start(job)
        return job

    def job_done(self,job):
        self.jobs.discard(job)
        if not self.jobs:
            self.progress.setRange(0,1)
            self.progress.setValue(1)
            if self.closing:
                self.close()

    def error(self,text):
        if self.closing:
            return
        message=explain_error(text)
        self.status.setText(message.replace('\n\n',' '))
        self.store.action('application','failed',{'error':text})
        if hasattr(self,'activity'): self.refresh_activity()
        dialog=QMessageBox(QMessageBox.Icon.Warning,'Operation could not complete',message,parent=self)
        dialog.setDetailedText(text)
        dialog.exec()

    def confirm(self,title,text):
        return QMessageBox.question(self,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def open_url(self,url):
        if not QDesktopServices.openUrl(QUrl(url)):
            self.error('Windows could not open '+url)

    def make_dashboard(self):
        l=self.page('Your workstation, in view','LIVE  •  refreshed asynchronously  •  sensor availability depends on hardware and installed providers')
        self.live_badge=StatusBadge('loading','Live telemetry: starting')
        l.addWidget(self.live_badge)
        grid=QGridLayout()
        self.metrics={}
        for i,(key,title) in enumerate([('cpu','CPU utilization'),('gpu','GPU utilization'),('ram','Memory utilization'),('network','Network latency')]):
            card=QFrame(); card.setObjectName('card')
            box=QVBoxLayout(card)
            box.setContentsMargins(16,16,16,16)
            box.setSpacing(10)
            box.addWidget(label(title,'muted'))
            value=label('Waiting…','metric'); detail=label('Reading current system…','muted')
            value.setFixedHeight(38)
            value.setAccessibleName(title)
            detail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            box.addWidget(value); box.addWidget(detail,1)
            self.metrics[key]=(value,detail)
            grid.addWidget(card,0,i)
            grid.setColumnStretch(i,1)
        l.addLayout(grid)
        charts=QHBoxLayout()
        self.cpu_chart=Chart('CPU utilization · %')
        self.gpu_chart=Chart('GPU utilization · %','#a9a0ff')
        self.net_chart=Chart('Download throughput · MiB/s','#66bbff',None)
        for c in (self.cpu_chart,self.gpu_chart,self.net_chart): charts.addWidget(c)
        l.addLayout(charts)
        self.system_summary=label('Scanning hardware…','muted')
        l.addWidget(self.system_summary)
        self.volumes=table(['Volume','Capacity (GiB)','Free (GiB)','Used','I/O telemetry'])
        l.addWidget(self.volumes,1)
        self.hardware_text=ResultView(); self.hardware_text.setMaximumHeight(200)
        l.addWidget(self.hardware_text)
        l.addWidget(button('Rescan hardware & current storage',self.scan_hardware))

    def poll(self):
        if self.closing or self.telemetry_busy: return
        self.telemetry_busy=True
        job=self.launch(lambda _:self.telemetry.sample(),self.show_telemetry,False,channel='telemetry')
        job.signals.done.connect(lambda:setattr(self,'telemetry_busy',False))

    def show_telemetry(self,s):
        if self.closing: return
        gpu=s.get('gpu',{})
        self.live_badge.set_status('ok','Live telemetry: updating asynchronously')
        self.metrics['cpu'][0].setText(fmt(s['cpu'],'%'))
        self.metrics['cpu'][1].setText(f"{fmt(s['cpu_mhz'],' MHz',0)} · {fmt(s['cpu_temp'],' °C')}\nClock is OS-reported; boost needs a hardware sensor.")
        self.metrics['gpu'][0].setText(fmt(gpu.get('utilization'),'%'))
        self.metrics['gpu'][1].setText(f"{fmt(gpu.get('temperature'),' °C')} · {fmt(gpu.get('clock'),' MHz',0)}\nVRAM {fmt(gpu.get('memory_used'),' MiB',0)} / {fmt(gpu.get('memory_total'),' MiB',0)}")
        self.metrics['ram'][0].setText(fmt(s['ram'],'%'))
        speeds=sorted({str(x.get('ConfiguredClockSpeed','?')) for x in self.hardware.get('memory',[])})
        self.metrics['ram'][1].setText(f"{s['ram_used']/2**30:.1f} / {s['ram_total']/2**30:.1f} GiB · {' / '.join(speeds) or '?'} MT/s")
        n=s['network']
        self.metrics['network'][0].setText(fmt(n['latency_ms'],' ms'))
        self.metrics['network'][1].setText(f"Jitter {fmt(n['jitter_ms'],' ms')} · loss {fmt(n['loss_percent'],'%')}\n1.1.1.1 · {n['sent']} rolling probes")
        self.cpu_chart.add(s['cpu']); self.gpu_chart.add(gpu.get('utilization')); self.net_chart.add(s['download']/2**20)
        self.system_summary.setText(f"Uptime {int(s['uptime']//3600)}h {int(s['uptime']%3600//60)}m  ·  {s['processes']} processes  ·  ↓ {s['download']/2**20:.2f} MiB/s  ↑ {s['upload']/2**20:.2f} MiB/s  ·  Disk aggregate: read {fmt(s['disk_read']/2**20 if s['disk_read'] is not None else None,' MiB/s')} / write {fmt(s['disk_write']/2**20 if s['disk_write'] is not None else None,' MiB/s')} · busy {fmt(s['disk_busy'],'%')}")
        fill(self.volumes,[(v['path'],f"{v['total']/2**30:.1f}",f"{v['free']/2**30:.1f}",f"{v['percent']}%",'Device health in hardware inventory below') for v in s['volumes']])

    def scan_hardware(self):
        if self.closing: return
        self.status.setText('Reading CIM hardware, pagefile policy and storage health…')
        self.launch(lambda _:inventory(),self.hardware_ready,channel='hardware')

    def hardware_ready(self,data):
        if self.closing: return
        self.hardware=data
        self.store.set('hardware',data)
        self.hardware_text.set_data(data)
        self.status.setText('Hardware scan complete. Unsupported sensors are labeled unavailable.')
        self.refresh_cards()

    def make_optimizations(self):
        l=self.page('Optimization Center','Evidence-led actions • Previous settings are saved before reversible changes • No automatic system modifications')
        row=QHBoxLayout()
        self.filter=QComboBox(); self.filter.addItems(['All','Recommended','Critical','Applied','Failed','Up-to-date'])
        self.filter.currentTextChanged.connect(self.refresh_cards)
        row.addWidget(self.filter)
        row.addWidget(button('Apply selected compatible actions',self.apply_selected,True))
        row.addWidget(button('Rescan configuration',self.scan_hardware))
        l.addLayout(row)
        area=QScrollArea(); area.setWidgetResizable(True)
        self.card_body=QWidget(); self.card_layout=QVBoxLayout(self.card_body)
        area.setWidget(self.card_body); l.addWidget(area,1)
        self.refresh_cards()

    def definitions(self):
        h=self.hardware
        power=h.get('power','Scan pending')
        prior='Prior user-provided diagnostics; causality unproven. '
        drivers='Installed driver versions: Driver Manager. Latest official release: not yet verified.'
        pagefile=explain_result({'pagefile_policy':h.get('pagefile_policy',[]),'pagefile_usage':h.get('pagefile_usage',[])})
        board=(h.get('board') or [{}])[0].get('Product','Unknown model')
        return [
            ('NVIDIA graphics / hibernation','Review a compatible official driver release; install with the vendor installer, then repeat hibernation tests.',drivers,prior+'Three RTX 2060 power-down path crashes. An update is a candidate intervention, not a proven fix.','Moderate','Recommended',None,OFFICIAL['NVIDIA graphics']),
            ('Realtek audio / shutdown','Review the exact-board ASUS audio driver and repeat shutdown tests.',drivers,prior+'One shutdown crash blocked the audio path.','Moderate','Recommended',None,OFFICIAL['ASUS board / audio / LAN / Wi-Fi / Bluetooth']),
            ('AMD chipset','Compare installed chipset package with the applicable AMD AM4 B550 release.',drivers,prior+'Storage and power transition findings make chipset compatibility relevant. Per-device versions do not equal chipset package versions.','Moderate','Recommended',None,OFFICIAL['AMD chipset']),
            ('Storage maintenance','Run Windows media-aware Optimize Drives on the system volume.',explain_result(h.get('disks',[])),prior+'Two SATA/storage-path analyses. Optimization does not repair controller faults; review errors and benchmark latency. No personal files are deleted.','Low','Recommended','storage',None),
            ('Pagefile configuration','Use Windows system-managed paging; restart later to activate allocation changes.',pagefile,prior+'Paging waits occurred. Check commit limit and disk latency; system-managed sizing is not proof of a crash fix. Previous policy and manual sizes are saved for rollback.','Moderate','Recommended','pagefile',None),
            ('Balanced power management','Use the standard Windows Balanced plan for daily use, then test transitions.',power,'Balances idle power and boost demand. No guaranteed FPS gain. Previous active plan is saved.','Low','Recommended' if BALANCED not in power.lower() else 'Up-to-date','balanced',None),
            ('CPU / quantitative throughput','Optionally test High performance for sustained compute, then compare identical workloads.',power,'Can raise idle power and heat without improving throughput. Mutually exclusive with Balanced. Revert restores the saved active plan.','Moderate','All','performance',None),
            ('Wi-Fi / Bluetooth / LAN','Use the exact motherboard support page; match hardware IDs before installing.',drivers,'Official board drivers preserve device-specific compatibility. No unverified latest version is claimed.','Moderate','All',None,OFFICIAL['ASUS board / audio / LAN / Wi-Fi / Bluetooth']),
            ('BIOS / firmware',f'Check official firmware and instructions for detected board: {board}.',explain_result(h.get('bios',[])),'Exact model required. Board variants are not interchangeable. Flash manually only after verifying model, release notes and recovery instructions.','High','All',None,firmware_url(board)),
            ('Windows updates','Review available updates in Windows Update; OS upgrades require separate explicit approval.',explain_result(h.get('os',[])),'Update metadata is obtained from the local Windows Update Agent when you click Check updates. Nothing installs automatically.','Moderate','All',None,OFFICIAL['Windows Update']),
            ('Startup applications','Review each entry and disable only unnecessary current-user entries.','Live list on Startup & Processes','Reversible backups are supported for current-user Registry Run entries. Security, hardware, cooling and game components are protected.','Low','All',None,'page:5'),
            ('Background software','Identify high-resource applications and explicitly close selected applications.','Live process CPU and memory on Startup & Processes','No automatic service changes or software removal. Xilinx uninstall is already complete; projects remain protected.','Moderate','All',None,'page:5'),
            ('GPU settings / gaming','Use NVIDIA Control Panel per-game settings and capture a repeatable scene with PresentMon.','Vendor defaults are retained','Measure FPS and frametimes before any per-game change. Global registry tweaks and security disablement are excluded.','Low','All',None,'page:3'),
            ('Network diagnostics','Benchmark latency, jitter and loss before changing adapter settings. Optionally flush DNS only for stale DNS issues.','ICMP and throughput live on Overview','DNS flushing refreshes name-resolution cache; it is not a ping optimization. It cannot fix packet loss or poor Wi-Fi signal.','Low','All','dns',None),
            ('Windows integrity','Run SFC /verifyonly; review findings before attempting any repair.','Not scanned this session; results in Activity','Read-only protected system file verification. Does not modify development projects or personal files.','Low','All','integrity',None),
            ('Windows image health','Run DISM /ScanHealth to inspect component-store health.','Not scanned this session; results in Activity','Diagnostic scan, not an OS upgrade or automatic repair. This may take several minutes.','Low','All','image_health',None),
            ('C++ development environment','Install official C++ Build Tools if needed and benchmark compilation.',h.get('compiler') or 'No supported compiler on PATH','A deterministic compilation workload measures toolchain throughput. Existing FPGA projects and external source files are untouched.','Low','Recommended' if not h.get('compiler') else 'Up-to-date',None,OFFICIAL['C++ Build Tools']),
            ('Quantitative research workloads','Use CPU/memory benchmarks and compare reproducible runs; retain datasets and environments.','No dataset or project directories scanned','Control parallel worker count and memory pressure in your workload. This app does not change environment variables or research files.','Low','All',None,'page:3'),
        ]

    def refresh_cards(self,*_):
        if not hasattr(self,'card_layout'): return
        while self.card_layout.count():
            child=self.card_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.cards=[]
        wanted=self.filter.currentText()
        latest={}
        for a in self.store.actions(): latest.setdefault(a['action'],a)
        for title,rec,current,evidence,risk,status,action,url in self.definitions():
            log=latest.get(action)
            if log and log['status'] in ('applied','failed'): status=log['status'].title()
            if wanted!='All' and wanted!=status: continue
            frame=QFrame(); frame.setObjectName('card')
            box=QVBoxLayout(frame)
            header=QHBoxLayout()
            check=QCheckBox(title); check.setFont(QFont('Segoe UI',13,QFont.Weight.DemiBold)); check.setEnabled(bool(action))
            header.addWidget(check,1); header.addWidget(label(f'{status}  ·  {risk} risk','muted')); box.addLayout(header)
            box.addWidget(label('Current: '+str(current)[:1300],'muted'))
            box.addWidget(label('Recommended: '+rec))
            box.addWidget(label('Evidence / expected benefit: '+evidence,'muted'))
            result=(log['payload'].get('output') or log['payload'].get('error') or '') if log else 'No action executed. Performance difference: not measured; use linked benchmark runs.'
            box.addWidget(label('Verification: '+result[:700],'muted'))
            controls=QHBoxLayout()
            apply=button('Apply' if action else 'Review / official action',lambda a=action,u=url,t=title:self.apply_action(a,u,t),bool(action))
            apply.setEnabled(not self.action_busy)
            controls.addWidget(apply)
            rev=button('Revert',lambda a=action:self.run_actions([a],True))
            rev.setEnabled(action in ('balanced','performance','pagefile') and bool(self.store.get('rollback:'+str(action))) and not self.action_busy)
            controls.addWidget(rev)
            controls.addWidget(label('Progress and complete command output appear below and in Activity.','muted'),1)
            box.addLayout(controls)
            self.card_layout.addWidget(frame)
            self.cards.append((check,action))
        self.card_layout.addStretch()

    def apply_action(self,action,url,title):
        if action:
            self.run_actions([action]); return
        if url=='sysdm.cpl':
            if self.confirm('Review pagefile settings','Open System Properties → Advanced → Performance Settings → Advanced → Virtual memory. Review system-managed paging. Windows will ask you to confirm changes; a reboot may be required.'):
                self.launch(lambda _:run(['control.exe','sysdm.cpl']))
        elif url and url.startswith('page:'):
            self.nav.setCurrentRow(int(url.split(':')[1]))
        elif url:
            if ('BIOS' in title or 'firmware' in title) and not self.confirm('Firmware review only','Open exact-model official instructions? Verify the physical motherboard model before downloading. This app never flashes firmware.'):
                return
            self.open_url(url)

    def apply_selected(self):
        selected=[action for check,action in self.cards if check.isChecked() and action]
        if not selected:
            QMessageBox.information(self,'Select actions','Select one or more executable optimization cards.'); return
        if 'balanced' in selected and 'performance' in selected:
            QMessageBox.warning(self,'Incompatible selection','Balanced and High performance are mutually exclusive. Select one.'); return
        self.run_actions(selected)

    def run_actions(self,selected,revert=False):
        if self.action_busy or self.benchmark:
            QMessageBox.information(self,'Work in progress','Wait for the active action or benchmark to finish.'); return
        if any(a not in ('balanced','performance') for a in selected) and not is_admin():
            QMessageBox.information(self,'Administrator session required','Use Restart as administrator in Activity & Settings. Windows UAC will ask for permission. Then initiate the action again.'); return
        if not self.confirm('Confirm '+('rollback' if revert else 'actions'),('Restore saved configuration for: ' if revert else 'Execute these actions: ')+', '.join(selected)+'?\nNo performance improvement is assumed. Run a baseline first for a valid comparison.'):
            return
        self.action_busy=True; self.refresh_cards()
        def execute(progress):
            output=[]
            for a in selected:
                output.append(a+': '+(self.engine.revert_pagefile(progress) if a=='pagefile' and revert else self.engine.execute(a,progress,revert)))
            return '\n\n'.join(output)
        job=self.launch(execute,lambda out:self.show_output('Action results',out))
        job.signals.done.connect(self.actions_done)

    def actions_done(self):
        self.action_busy=False
        self.refresh_cards(); self.refresh_activity()
        self.scan_hardware()

    def show_output(self,title,output):
        self.status.setText(title+' · complete')
        self.activity.set_data(output)

    def make_drivers(self):
        l=self.page('Driver Manager','Installed versions from signed PnP inventory • Available releases remain unverified until matched to official device and OS support')
        controls=QHBoxLayout()
        controls.addWidget(button('Scan installed drivers',self.scan_drivers,True))
        controls.addWidget(button('Check Windows Update metadata',self.check_updates))
        self.driver_filter=QLineEdit(); self.driver_filter.setPlaceholderText('Filter devices, providers, hardware IDs…')
        self.driver_filter.textChanged.connect(self.render_drivers); controls.addWidget(self.driver_filter,1)
        l.addLayout(controls)
        self.driver_table=table(['Device','Installed version','Driver date','Provider','Available version','Status / OS','Hardware ID'])
        l.addWidget(self.driver_table,1)
        self.driver_info=ResultView(); self.driver_info.setMaximumHeight(190)
        self.driver_info.setPlainText('Click Check Windows Update metadata for applicable update offers. Official vendor pages provide release versions, release dates and OS support. Windows Update titles may omit a version; the app will not infer it. Driver installation remains in the official installer or Windows Update, with its own approval and rollback workflow.')
        l.addWidget(self.driver_info)
        self.vendor=QComboBox(); self.vendor.addItems(list(OFFICIAL)[:4])
        row=QHBoxLayout(); row.addWidget(self.vendor); row.addWidget(button('Official download / installation',lambda:self.open_url(OFFICIAL[self.vendor.currentText()])))
        row.addWidget(button('Device Manager / driver rollback',lambda:self.launch(lambda _:run(['mmc.exe','devmgmt.msc']))))
        l.addLayout(row)

    def scan_drivers(self):
        self.status.setText('Reading installed signed PnP driver inventory…')
        self.launch(lambda _:driver_inventory(),self.drivers_ready)

    def drivers_ready(self,data):
        self.drivers=data
        self.store.set('drivers',data)
        self.render_drivers()
        self.status.setText(f'{len(data)} drivers detected. Vendor latest versions are not assumed.')

    def render_drivers(self,*_):
        term=self.driver_filter.text().casefold()
        data=[d for d in self.drivers if term in json.dumps(d).casefold()]
        fill(self.driver_table,[(d.get('DeviceName'),d.get('DriverVersion'),d.get('DriverDate'),d.get('DriverProviderName'),
                                'Not verified','Manual vendor comparison / OS compatibility required',d.get('DeviceID')) for d in data])

    def check_updates(self):
        self.status.setText('Searching applicable Windows Update metadata; may take several minutes…')
        self.launch(lambda _:update_search(),self.updates_ready)

    def updates_ready(self,data):
        self.updates=data
        self.store.set('update_offers',dict(checked=timestamp(),updates=data))
        self.driver_info.set_data(data if data else 'Windows Update reports no currently offered updates. This does not establish that all vendor drivers are current.')
        self.status.setText(f'{len(data)} applicable update offers found. No downloads or installations initiated.')

    def make_benchmarks(self):
        l=self.page('Benchmark Center','Repeatable real workloads • Three repeats where applicable • Close other workloads before measuring')
        grid=QGridLayout(); self.test_checks={}
        for i,(key,(name,unit,higher)) in enumerate(TESTS.items()):
            c=QCheckBox(name); c.setChecked(key in ('cpu_single','cpu_multi','memory','network','idle'))
            grid.addWidget(c,i//2,i%2); self.test_checks[key]=c
        l.addLayout(grid)
        l.addWidget(label('Storage: 64 MiB bounded file on the app volume, cached I/O, sequential + 4 KiB random read/write. CPU: Python SHA-256 chains, up to 4 workers. Memory: 32 MiB Python buffer copies. These are workload measurements, not vendor performance ratings.','muted'))
        row=QHBoxLayout()
        for title,kind in [('Run Baseline','baseline'),('Run Selected Benchmarks','selected'),('Run Post-Optimization Benchmark','post')]:
            row.addWidget(button(title,lambda k=kind:self.run_benchmarks(k),True))
        row.addWidget(button('Cancel',self.cancel_benchmarks)); l.addLayout(row)
        self.bench_table=table(['Test','Median','Unit','Repeated samples','Additional measurements / availability'])
        l.addWidget(self.bench_table,1)
        tools=QHBoxLayout()
        tools.addWidget(button('GPU benchmark · official UNIGINE tool',lambda:self.open_url(OFFICIAL['GPU benchmark (UNIGINE)'])))
        tools.addWidget(button('Gaming · official PresentMon',lambda:self.open_url(OFFICIAL['PresentMon'])))
        tools.addWidget(button('Import single-game PresentMon CSV',self.import_gaming))
        l.addLayout(tools)
        l.addWidget(label('GPU scoring unavailable without an external benchmark; no invented score. Gaming capture is imported from PresentMon. Boot timing reads the latest event and does not reboot. C++ requires a compiler on PATH.','muted'))
        l.addWidget(button('Compare Results',lambda:(self.refresh_history(),self.nav.setCurrentRow(4))))

    def run_benchmarks(self,kind):
        if self.benchmark or self.action_busy:
            QMessageBox.information(self,'Work in progress','Wait for the active benchmark or action.'); return
        selected=[key for key,c in self.test_checks.items() if c.isChecked()]
        if not selected:
            QMessageBox.information(self,'Select benchmarks','Select at least one test.'); return
        if not self.hardware.get('cpu'):
            QMessageBox.information(self,'Scan required','Wait for a successful current hardware scan before benchmarking.'); return
        if not self.confirm('Start benchmark','Run '+', '.join(selected)+'?\nThis creates CPU and disk load. Files are bounded to the app test directory and deleted afterward.'):
            return
        self.benchmark=BenchmarkEngine(self.store,self.hardware,ROOT/'data'/'benchmark-temp')
        engine=self.benchmark
        job=self.launch(lambda progress:engine.suite(selected,kind,progress),self.bench_done)
        job.signals.done.connect(lambda:setattr(self,'benchmark',None))

    def cancel_benchmarks(self):
        if self.benchmark:
            self.benchmark.cancel.set(); self.status.setText('Cancellation requested; finishing the current bounded operation…')

    def bench_done(self,data):
        display=[]
        for key,v in data['results'].items():
            extra={k:x for k,x in v.items() if k not in ('value','unit','samples','higher','cv')}
            display.append((TESTS.get(key,(readable_label(key),))[0],fmt(v['value']),v['unit'],', '.join(fmt(x) for x in v['samples']),explain_result(extra)))
        for key,error in data['errors'].items(): display.append((TESTS.get(key,(readable_label(key),))[0],'Unavailable','—','—',error))
        fill(self.bench_table,display)
        self.status.setText(f"Run #{data['id']} saved locally with hardware, parameters and action history.")
        self.refresh_history()

    def import_gaming(self):
        path,_=QFileDialog.getOpenFileName(self,'Import PresentMon CSV','','CSV (*.csv)')
        if not path: return
        identity,ok=QInputDialog.getText(self,'Capture protocol','Enter game, resolution, quality preset, scene and capture duration. Use exactly the same description for comparisons:')
        if not ok or not identity.strip(): return
        def task(_):
            m=import_presentmon(path,identity.strip())
            payload=dict(hardware=self.hardware,fingerprint=fingerprint(self.hardware),parameters={'protocol':'PresentMon import v1'},
                         results={'gaming':m},errors={},optimization_state=self.store.actions()[:100],complete=True)
            payload['id']=self.store.save_run('gaming capture',payload)
            return payload
        self.launch(task,self.bench_done)

    def make_compare(self):
        l=self.page('Before & After','Performance and stability are separate outcomes • Comparisons require matching hardware, OS, drivers and test parameters')
        row=QHBoxLayout()
        self.before=QComboBox(); self.after=QComboBox()
        row.addWidget(label('Baseline')); row.addWidget(self.before,1); row.addWidget(label('Current')); row.addWidget(self.after,1)
        row.addWidget(button('Compare Results',self.compare,True)); row.addWidget(button('Refresh',self.refresh_history))
        l.addLayout(row)
        self.compare_table=table(['Test','Baseline','Current','Absolute change','Change %','Interpretation'])
        l.addWidget(self.compare_table,1)
        self.history_chart=Chart('History · selected metric (chronological)','#a9a0ff',None)
        l.addWidget(self.history_chart)
        self.history_metric=QComboBox()
        for key in list(TESTS)+['gaming']:
            self.history_metric.addItem(TESTS.get(key,('Gaming capture',))[0],key)
        self.history_metric.currentTextChanged.connect(self.draw_history)
        l.addWidget(self.history_metric)
        self.comparison_info=ResultView(); self.comparison_info.setMaximumHeight(220)
        l.addWidget(self.comparison_info)
        self.refresh_history()

    def refresh_history(self):
        if not hasattr(self,'before'): return
        self.runs=[r for r in self.store.runs() if not r['kind'].startswith('network ')]
        old_before=self.before.currentData(); old_after=self.after.currentData()
        self.before.clear(); self.after.clear()
        for r in self.runs:
            if 'results' in r['payload']:
                title=f"#{r['id']} · {r['kind']} · {r['created']}"
                self.before.addItem(title,r['id']); self.after.addItem(title,r['id'])
        idx=self.before.findData(old_before)
        if idx<0:
            baselines=[r['id'] for r in self.runs if r['kind']=='baseline']
            idx=self.before.findData(baselines[0]) if baselines else self.before.count()-1
        self.before.setCurrentIndex(idx)
        idx=self.after.findData(old_after)
        self.after.setCurrentIndex(max(0,idx))
        self.draw_history()

    def draw_history(self,*_):
        if not hasattr(self,'history_metric'): return
        key=self.history_metric.currentData()
        self.history_chart.title='History · '+self.history_metric.currentText()+' (chronological; inspect protocols before comparing)'
        self.history_chart.values.clear()
        for r in reversed(self.runs):
            value=r['payload'].get('results',{}).get(key,{}).get('value')
            if value is not None: self.history_chart.add(value)
        self.history_chart.update()

    def compare(self):
        a=next((r for r in self.runs if r['id']==self.before.currentData()),None)
        b=next((r for r in self.runs if r['id']==self.after.currentData()),None)
        if not a or not b or a['id']==b['id']:
            QMessageBox.information(self,'Select two runs','Choose two different saved benchmark runs.'); return
        comparisons=compare_runs(a,b)
        fill(self.compare_table,[(TESTS.get(v['test'],(readable_label(v['test']),))[0],fmt(v['baseline'])+' '+v['unit'],fmt(v['current'])+' '+v['unit'],
                                 fmt(v['absolute']),fmt(v['percent'],'%'),v['status']) for v in comparisons])
        info={'comparison_rule':'3% minimum noise band or 2 × combined within-run coefficient of variation. Heuristic, not statistical proof. Driver or OS changes invalidate controlled comparisons; results remain visible.',
              'baseline_action_history':a['payload'].get('optimization_state',[]),
              'current_action_history':b['payload'].get('optimization_state',[])}
        self.comparison_info.set_data(info)

    def make_processes(self):
        l=self.page('Startup & Processes','Explicit choices only • Current-user Registry Run rollback • Protected system, security, cooling and game components cannot be changed')
        row=QHBoxLayout()
        row.addWidget(button('Refresh processes',self.refresh_processes,True))
        row.addWidget(button('Inspect selected publisher',self.inspect_process))
        row.addWidget(button('Close selected application',self.close_process))
        l.addLayout(row)
        self.process_table=table(['PID','Application','CPU %','Memory (MiB)','User','Executable / publisher inspection'])
        l.addWidget(self.process_table,1)
        row=QHBoxLayout()
        row.addWidget(button('Scan startup entries',self.refresh_startups))
        row.addWidget(button('Disable selected entry',lambda:self.change_startup(False)))
        row.addWidget(button('Restore selected saved entry',lambda:self.change_startup(True)))
        row.addWidget(button('Windows Startup Settings',lambda:self.open_url('ms-settings:startupapps')))
        l.addLayout(row)
        self.startup_table=table(['Name','Command','Scope','Source','State'])
        l.addWidget(self.startup_table,1)
        l.addWidget(label('CPU is measured between process refreshes; refresh twice to identify sustained load. Publisher is inspected on demand from file metadata and Authenticode signature.','muted'))

    def refresh_processes(self):
        self.launch(lambda _:process_list(),self.processes_ready)

    def processes_ready(self,data):
        self.processes=data
        fill(self.process_table,[(p['pid'],p['name'],p['cpu'],f"{p['memory']/2**20:.1f}",p['user'],p['exe']) for p in data])

    def inspect_process(self):
        i=self.process_table.currentRow()
        if i<0: return
        item=self.processes[i]
        self.launch(lambda _:publisher(item['exe']),lambda out:QMessageBox.information(self,'Publisher information',explain_result(out)))

    def close_process(self):
        i=self.process_table.currentRow()
        if i<0: return
        item=self.processes[i].copy()
        if self.confirm('Close application',f"Terminate {item['name']} (PID {item['pid']})? Unsaved work can be lost. Save work first. Protected components are blocked."):
            def close(_):
                result=terminate_process(item)
                self.store.action('close_process','applied',item)
                return result
            self.launch(close,lambda out:(self.show_output('Process result',out),self.refresh_processes()))

    def refresh_startups(self):
        self.launch(lambda _:startup_entries()+[{**x,'disabled':True} for x in disabled_startups(self.store)],self.startups_ready)

    def startups_ready(self,data):
        self.startups=data
        fill(self.startup_table,[(x['name'],x['command'],x['scope'],x['source'],'Disabled (backup saved)' if x.get('disabled') else 'Enabled') for x in data])

    def change_startup(self,restore):
        i=self.startup_table.currentRow()
        if i<0:return
        item=self.startups[i].copy()
        if restore!=bool(item.get('disabled')):
            QMessageBox.information(self,'Entry state','Select a disabled saved entry to restore, or an enabled entry to disable.'); return
        if self.confirm('Confirm startup change',('Restore ' if restore else 'Disable ')+item['name']+'? The saved command is retained for rollback.'):
            self.launch(lambda _:startup_change(self.store,item,restore),lambda out:(self.show_output('Startup result',out),self.refresh_startups()))

    def make_stability(self):
        l=self.page('Stability Center','Prior evidence is imported once • New observations do not establish driver causality • Desktop interruption tests require your confirmation')
        evidence=self.store.get('prior_evidence')
        summary=QTextEdit(); summary.setReadOnly(True); summary.setMaximumHeight(165)
        summary.setPlainText(evidence['source']+' (not independently re-analyzed)\n\n'+'\n'.join('• '+x for x in evidence['findings']))
        l.addWidget(summary)
        row=QHBoxLayout()
        row.addWidget(button('Scan recent crash / error events',self.scan_events,True))
        row.addWidget(button('Observe paging & disk latency · 10 s',self.observe_stability))
        row.addWidget(button('CPU / GPU performance tests',lambda:self.nav.setCurrentRow(3)))
        l.addLayout(row)
        row=QHBoxLayout()
        self.transition=QComboBox(); self.transition.addItems(['restart','shutdown','sleep','hibernate'])
        row.addWidget(self.transition)
        row.addWidget(button('Initiate desktop transition test',self.begin_transition))
        row.addWidget(button('Cancel scheduled transition',self.cancel_transition))
        row.addWidget(button('Collect saved transition result',self.collect_transition))
        l.addLayout(row)
        self.stability_output=ResultView()
        pending=self.store.get('pending_transition')
        self.stability_output.set_data({'saved_transition_awaiting_collection':pending} if pending else 'No transition test pending. Run a test before collecting new stability evidence.\n\nShutdown duration requires a Diagnostics-Performance event 200 after the next boot. Total wall time includes time powered off and is never labeled shutdown completion time. Sleep/hibernate success requires your observation plus event review.')
        l.addWidget(self.stability_output,1)
        row=QHBoxLayout()
        row.addWidget(button('Open dump in local WinDbg',self.open_dump))
        row.addWidget(button('Official WinDbg installation',lambda:self.open_url(OFFICIAL['WinDbg'])))
        row.addWidget(button('Windows integrity actions',lambda:self.nav.setCurrentRow(1)))
        l.addLayout(row)

    def scan_events(self):
        def work(_):
            events=event_scan()
            self.store.save_run('event observation',{'events':events,'captured_at':timestamp()})
            return events
        self.launch(work,self.stability_output.set_data)

    def observe_stability(self):
        def work(progress):
            out=stability.observe(progress=progress)
            self.store.save_run('stability observation',out)
            return out
        self.launch(work,self.stability_output.set_data)

    def begin_transition(self):
        if self.benchmark or self.action_busy:
            QMessageBox.information(self,'Work in progress','Finish actions and benchmarks before interrupting the desktop.'); return
        mode=self.transition.currentText()
        if not self.confirm('Interrupt desktop session',f"Initiate {mode}? Save all open work now. Restart and shutdown begin in 15 seconds. Sleep/hibernation begins immediately. A pending test is committed to disk first; this app will launch once at next sign-in for restart/shutdown.\n\nAfter resuming, collect the result and report whether the transition succeeded."):
            return
        self.launch(lambda _:stability.initiate(self.store,mode,ROOT),lambda out:self.stability_output.setPlainText(out))

    def cancel_transition(self):
        self.launch(lambda _:stability.cancel_transition(self.store),lambda out:self.stability_output.setPlainText(out))

    def collect_transition(self):
        if not self.store.get('pending_transition'):
            QMessageBox.information(self,'No saved test','Initiate a transition test first.'); return
        answer=QMessageBox.question(self,'Transition outcome','Did the requested transition and return to the desktop complete successfully?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
        if answer==QMessageBox.StandardButton.Cancel:return
        self.launch(lambda _:stability.collect(self.store,answer==QMessageBox.StandardButton.Yes),self.stability_output.set_data)

    def open_dump(self):
        debugger=self.hardware.get('windbg')
        if not debugger:
            QMessageBox.information(self,'WinDbg unavailable','Install WinDbg from the official link. Existing dump conclusions are already imported.'); return
        path,_=QFileDialog.getOpenFileName(self,'Open an existing dump (analysis is local)','','Crash dump (*.dmp)')
        if path:
            import subprocess
            subprocess.Popen([debugger,'-z',path])

    def make_activity(self):
        l=self.page('Activity & Settings','Local SQLite persistence • Executed commands, verification output, rollback state and benchmark history')
        row=QHBoxLayout()
        row.addWidget(button('Refresh action history',self.refresh_activity,True))
        row.addWidget(button('Restart as administrator · UAC',self.elevate))
        row.addWidget(button('Open local data folder',lambda:self.open_url(QUrl.fromLocalFile(str(self.store.path.parent)).toString())))
        l.addLayout(row)
        self.activity=ResultView()
        l.addWidget(self.activity,1)
        l.addWidget(label(f'PC Optimizer {__version__} · Database: {self.store.path}\nNo action is applied at launch. Live ICMP probes go to the IPv4 gateway and 1.1.1.1. Network benchmarks send bounded synthetic traffic only after consent. Windows Update checks are initiated manually.','muted'))
        self.refresh_activity()

    def refresh_activity(self):
        if hasattr(self,'activity'):
            self.activity.set_data(self.store.actions())

    def elevate(self):
        if is_admin():
            QMessageBox.information(self,'Already elevated','This session already has administrator rights.');return
        if self.jobs:
            QMessageBox.information(self,'Wait for work','Wait for background tasks to finish before restarting.');return
        code=ctypes.windll.shell32.ShellExecuteW(None,'runas',sys.executable,'"'+str(ROOT/'main.py')+'"',str(ROOT),1)
        if code<=32:
            QMessageBox.warning(self,'Elevation cancelled','Windows did not start an administrator session. No action was applied.');return
        self.timer.stop()
        self.close()

    def closeEvent(self,event):
        if self.action_busy or self.benchmark:
            QMessageBox.information(self,'Operation running','Finish or cancel the active operation before closing.'); event.ignore();return
        self.timer.stop()
        self.network_center.stop()
        if hasattr(self,'ai_panel'):
            self.ai_panel.stop()
        if hasattr(self,'ai_optimizer'):
            self.ai_optimizer.stop()
        self.closing=True
        self.requests.invalidate()
        # Keep signal receivers alive until every bounded read-only worker completes.
        # Accepting close after an arbitrary 5 s wait could destroy a running job's signals.
        if self.jobs:
            self.hide()
            event.ignore()
            return
        self.store.set('window_size',[self.width(),self.height()])
        event.accept()
