"""Optional local-AI presentation helpers and worker-safe request tracking.

UI owns scheduling, cancellation, stale-response suppression, and display.
Backend `optimizer.ai.recommend` is imported only when present on the
integration base; otherwise the panel reports a clear unavailable state.
No downloads, runtime installation, or automatic optimization occur here.
"""
from __future__ import annotations

import traceback
from threading import Event

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .readable_ui import ResultView, StatusBadge


# Presentation-only fixtures matching docs/local-ai/contract.md shapes.
SYNTHETIC_AI_RESULTS = {
    'unavailable': {
        'schema_version': 1,
        'status': 'unavailable',
        'source': 'deterministic',
        'model': None,
        'generated_at': '2026-11-24T22:00:00+00:00',
        'detail': 'No local model runtime is available in this session.',
        'evidence': {},
        'suggestions': [],
        'limitations': [
            'Advice is heuristic and uncertain.',
            'Diagnostics remain available without a model runtime.',
        ],
    },
    'ok': {
        'schema_version': 1,
        'status': 'ok',
        'source': 'local_llm',
        'model': 'fixture-model',
        'generated_at': '2026-11-24T22:00:00+00:00',
        'detail': 'Synthetic advisory response for UI tests.',
        'evidence': {'network.signal_percent': 42},
        'suggestions': [{
            'id': 'wifi-signal',
            'title': 'Compare a wired trial from the same location',
            'rationale': 'Reported signal quality is 42%.',
            'evidence': ['network.signal_percent'],
            'risk': 'low',
            'requires_approval': True,
            'source': 'local_llm',
        }],
        'limitations': ['Advice is heuristic and uncertain.'],
    },
    'error': {
        'schema_version': 1,
        'status': 'error',
        'source': 'deterministic',
        'model': None,
        'generated_at': '2026-11-24T22:00:00+00:00',
        'detail': 'The local runtime returned an unusable response.',
        'evidence': {},
        'suggestions': [],
        'limitations': ['Advice is heuristic and uncertain.'],
    },
    'canceled': {
        'schema_version': 1,
        'status': 'canceled',
        'source': 'deterministic',
        'model': None,
        'generated_at': '2026-11-24T22:00:00+00:00',
        'detail': 'Advisory request was canceled before completion.',
        'evidence': {},
        'suggestions': [],
        'limitations': ['Advice is heuristic and uncertain.'],
    },
}


def resolve_recommend(provider=None):
    """Return a recommend(snapshot, network_result=None, *, cancel=None) callable."""
    if provider is not None:
        return provider
    try:
        from optimizer.ai import recommend  # type: ignore
        return recommend
    except ImportError:
        return None


def unavailable_result(detail=None):
    result = dict(SYNTHETIC_AI_RESULTS['unavailable'])
    if detail:
        result['detail'] = detail
    return result


class CancelToken:
    """Thread-safe cancel flag compatible with the AI contract's cancel protocol."""

    def __init__(self):
        self._event = Event()

    def cancel(self):
        self._event.set()

    def is_set(self):
        return self._event.is_set()

    def __call__(self):
        return self._event.is_set()


class RequestGate(QObject):
    """Per-channel generation counter to drop stale worker callbacks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._generations = {}

    def next(self, channel):
        value = self._generations.get(channel, 0) + 1
        self._generations[channel] = value
        return value

    def current(self, channel):
        return self._generations.get(channel, 0)

    def invalidate(self, channel=None):
        if channel is None:
            for key in list(self._generations):
                self._generations[key] = self._generations.get(key, 0) + 1
            return
        self.next(channel)

    def accept(self, channel, generation):
        return self._generations.get(channel) == generation


class AiAdvisorPanel(QWidget):
    """Optional advisory panel; never installs runtimes or applies host changes."""

    request_started = Signal(int)
    request_finished = Signal(int)

    def __init__(self, host, provider=None, parent=None):
        super().__init__(parent)
        self.host = host
        self.provider = provider
        self.cancel_token = None
        self.busy = False
        self.closed = False
        self._channel = 'ai'
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        from .ui import label, button
        layout.addWidget(label('Local AI advice', 'title'))
        layout.addWidget(label(
            'Optional local advisory only • No cloud calls • No automatic downloads or optimization • '
            'Host changes still require explicit confirmation elsewhere',
            'muted'))
        self.runtime_badge = StatusBadge('unavailable', 'Runtime not checked yet')
        self.model_label = label('Selected runtime / model: not selected', 'muted')
        self.limits_label = label(
            'Resource limits: UI will not start a model runtime. When a backend is present, '
            'it enforces loopback-only HTTP, timeouts, and size bounds.',
            'muted')
        layout.addWidget(self.runtime_badge)
        layout.addWidget(self.model_label)
        layout.addWidget(self.limits_label)
        row = QHBoxLayout()
        self.refresh_button = button('Check advisory availability', self.refresh, True)
        self.cancel_button = button('Cancel advisory request', self.cancel)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.refresh_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.status = label('Diagnostics remain usable without a model runtime.', 'muted')
        layout.addWidget(self.status)
        self.suggestions = ResultView()
        layout.addWidget(self.suggestions, 1)
        self._show_result(unavailable_result(
            'Advisory engine not queried yet. Diagnostics and network tools remain available.'))

    def set_provider(self, provider):
        self.provider = provider

    def refresh(self):
        if self.closed or self.host.closing:
            return
        # A newer request supersedes any in-flight advisory worker.
        if self.cancel_token:
            self.cancel_token.cancel()
        recommend = resolve_recommend(self.provider)
        generation = self.host.requests.next(self._channel)
        self.busy = True
        self.refresh_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_token = CancelToken()
        self.status.setText('Checking local advisory availability off the UI thread…')
        self.runtime_badge.set_status('loading', 'Checking local runtime')
        self.request_started.emit(generation)
        snapshot = {
            'inventory': getattr(self.host, 'hardware', {}) or {},
            'network': getattr(self.host.network_center, 'snapshot', {}) or {},
        }
        network_result = getattr(self.host.network_center, 'intelligence', None)

        def work(_progress):
            if recommend is None:
                return unavailable_result(
                    'optimizer.ai is not present on this build. Install/start a local runtime later; '
                    'no download was attempted.')
            if self.cancel_token.is_set():
                return dict(SYNTHETIC_AI_RESULTS['canceled'])
            try:
                return recommend(snapshot, network_result=network_result, cancel=self.cancel_token)
            except ValueError as exc:
                result = unavailable_result(str(exc))
                result['status'] = 'error'
                return result
            except Exception:
                result = dict(SYNTHETIC_AI_RESULTS['error'])
                result['detail'] = 'Advisory worker failed; see Activity for technical details.'
                result['limitations'] = list(result['limitations']) + [traceback.format_exc()[-500:]]
                return result

        job = self.host.launch(work, None, True, channel=None)

        def on_result(result, expected=generation):
            if self.closed or self.host.closing or not self.host.requests.accept(self._channel, expected):
                return
            self._show_result(result)

        def on_done(expected=generation):
            if self.host.requests.accept(self._channel, expected):
                self.busy = False
                self.refresh_button.setEnabled(True)
                self.cancel_button.setEnabled(False)
                self.cancel_token = None
            self.request_finished.emit(expected)

        job.signals.result.connect(on_result)
        job.signals.error.connect(lambda text, expected=generation: on_result({
            **SYNTHETIC_AI_RESULTS['error'],
            'detail': 'Advisory worker failed.',
            'limitations': SYNTHETIC_AI_RESULTS['error']['limitations'] + [text[-500:]],
        }, expected))
        job.signals.done.connect(on_done)

    def cancel(self):
        if self.cancel_token:
            self.cancel_token.cancel()
            self.status.setText('Cancellation requested…')
            self.runtime_badge.set_status('canceled', 'Canceling advisory request')

    def _show_result(self, result):
        status = (result or {}).get('status', 'unavailable')
        detail = (result or {}).get('detail') or 'No advisory detail.'
        model = (result or {}).get('model') or 'none'
        source = (result or {}).get('source') or 'deterministic'
        self.runtime_badge.set_status(status, f'Advisory status: {status}')
        self.model_label.setText(f'Selected runtime / model: {model} · source {source}')
        self.status.setText(detail)
        suggestions = (result or {}).get('suggestions') or []
        limitations = (result or {}).get('limitations') or []
        cards = []
        for item in suggestions:
            cards.append({
                'title': item.get('title') or item.get('id'),
                'rationale': item.get('rationale'),
                'risk': item.get('risk'),
                'requires_approval': item.get('requires_approval', True),
                'evidence': item.get('evidence'),
            })
        payload = {
            'status': status,
            'detail': detail,
            'suggestions': cards,
            'limitations': limitations,
            'evidence': (result or {}).get('evidence') or {},
        }
        if not cards:
            payload['note'] = 'No advisory suggestions. Existing diagnostics remain usable.'
        self.suggestions.set_data(payload)

    def stop(self):
        self.closed = True
        self.cancel()
        self.host.requests.invalidate(self._channel)
