"""Dedicated AI Optimizer dashboard — presentation and worker scheduling only.

Coordinates with the Local AI backend contract (docs/local-ai/contract.md) for
advisory recommendations. Explorer, comparison, and coding-agent surfaces use
injectable providers; absent providers render Unavailable. Synthetic fixtures
must carry fixture_kind=synthetic_development and a visible UI banner.
Never downloads models, installs runtimes, or starts paid API calls.
"""
from __future__ import annotations

import traceback
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .ai_ui import (
    CancelToken, SYNTHETIC_AI_RESULTS, resolve_recommend, unavailable_result,
)
from .readable_ui import ResultView, StatusBadge


FIXTURE_KIND = 'synthetic_development'
FIXTURE_BANNER = 'Synthetic development fixture — not measured on this machine.'

UNAVAILABLE_INVENTORY = {
    'schema_version': 1,
    'fixture_kind': None,
    'providers': [],
    'runtimes': [],
    'workloads': [],
    'limitations': [
        'Provider inventory is unavailable until a backend inventory provider is configured.',
        'No model download, runtime install, or paid API call was attempted.',
    ],
    'detail': 'AI provider inventory unavailable.',
}

SYNTHETIC_INVENTORY = {
    'schema_version': 1,
    'fixture_kind': FIXTURE_KIND,
    'providers': [
        {
            'id': 'ollama-local',
            'name': 'Ollama',
            'kind': 'local',
            'availability': 'unknown',
            'detail': 'Fixture only; runtime was not probed.',
        },
        {
            'id': 'cloud-example',
            'name': 'Example cloud API',
            'kind': 'cloud',
            'availability': 'unavailable',
            'detail': 'Cloud calls are not initiated by this dashboard.',
        },
    ],
    'runtimes': [
        {
            'id': 'ollama',
            'endpoint': 'loopback-only (not contacted)',
            'status': 'unavailable',
            'detail': 'Synthetic fixture; no HTTP probe was performed.',
        },
    ],
    'workloads': [],
    'limitations': [FIXTURE_BANNER],
    'detail': 'Synthetic inventory for UI layout checks.',
}

UNAVAILABLE_CATALOG = {
    'schema_version': 1,
    'fixture_kind': None,
    'models': [],
    'limitations': [
        'Model catalog unavailable until a backend catalog provider is configured.',
        'No model metadata was invented for this session.',
    ],
    'detail': 'Model explorer data unavailable.',
}

SYNTHETIC_CATALOG = {
    'schema_version': 1,
    'fixture_kind': FIXTURE_KIND,
    'models': [
        {
            'name': 'fixture-local-3b',
            'parameters': '3B',
            'quantization': 'Q4_K_M',
            'context_window': 8192,
            'estimated_ram_gib': 4,
            'estimated_vram_gib': 3,
            'hardware_compatibility': 'Unknown on this host (fixture)',
            'execution': 'local',
        },
        {
            'name': 'fixture-cloud-large',
            'parameters': 'Unavailable',
            'quantization': 'n/a',
            'context_window': None,
            'estimated_ram_gib': None,
            'estimated_vram_gib': None,
            'hardware_compatibility': 'Cloud-hosted; local hardware N/A',
            'execution': 'cloud',
        },
    ],
    'limitations': [FIXTURE_BANNER],
    'detail': 'Synthetic catalog for UI layout checks.',
}

UNAVAILABLE_BENCHMARKS = {
    'schema_version': 1,
    'fixture_kind': None,
    'comparisons': [],
    'limitations': [
        'Benchmark comparison unavailable; no measured tokens/s, TTFT, quality, or cost data.',
        'This UI does not fabricate rankings or pricing.',
    ],
    'detail': 'Model comparison data unavailable.',
}

SYNTHETIC_BENCHMARKS = {
    'schema_version': 1,
    'fixture_kind': FIXTURE_KIND,
    'comparisons': [
        {
            'model': 'fixture-local-3b',
            'tokens_per_second': None,
            'time_to_first_token_ms': None,
            'memory_gib': None,
            'task_accuracy': None,
            'quality_score': None,
            'api_cost': 'n/a (local fixture)',
            'notes': 'Metrics intentionally null — fixture demonstrates Unavailable cells, not scores.',
        },
        {
            'model': 'fixture-cloud-large',
            'tokens_per_second': None,
            'time_to_first_token_ms': None,
            'memory_gib': None,
            'task_accuracy': None,
            'quality_score': None,
            'api_cost': 'Unavailable — paid APIs are not called',
            'notes': 'No paid API call was made to obtain cost or latency.',
        },
    ],
    'limitations': [FIXTURE_BANNER, 'Null metrics are Unavailable, not zero performance.'],
    'detail': 'Synthetic comparison skeleton for UI layout checks.',
}

UNAVAILABLE_AGENTS = {
    'schema_version': 1,
    'fixture_kind': None,
    'agents': [
        {'id': 'codex', 'name': 'Codex', 'status': 'unavailable', 'detail': 'No agent status provider.'},
        {'id': 'cursor', 'name': 'Cursor', 'status': 'unavailable', 'detail': 'No agent status provider.'},
        {'id': 'claude', 'name': 'Claude', 'status': 'unavailable', 'detail': 'No agent status provider.'},
    ],
    'issues': [],
    'branches': [],
    'worktrees': [],
    'pull_requests': [],
    'blockers': [],
    'model_recommendations': [],
    'limitations': [
        'Coding-agent status unavailable without a read-only status provider.',
        'GitHub/worktree data is not guessed.',
    ],
    'detail': 'Coding agent center unavailable.',
}

SYNTHETIC_AGENTS = {
    'schema_version': 1,
    'fixture_kind': FIXTURE_KIND,
    'agents': [
        {'id': 'codex', 'name': 'Codex', 'status': 'unknown', 'detail': 'Fixture — not a live session probe.'},
        {'id': 'cursor', 'name': 'Cursor', 'status': 'unknown', 'detail': 'Fixture — not a live session probe.'},
        {'id': 'claude', 'name': 'Claude', 'status': 'unknown', 'detail': 'Fixture — not a live session probe.'},
    ],
    'issues': [
        {'id': '#16', 'title': 'AI Optimizer dashboard', 'state': 'open', 'agent': 'cursor'},
    ],
    'branches': [
        {'name': 'codex/issue-16-ai-optimizer-dashboard', 'agent': 'cursor'},
    ],
    'worktrees': [
        {'path': '…/issue-16-ai-optimizer-dashboard', 'branch': 'codex/issue-16-ai-optimizer-dashboard'},
    ],
    'pull_requests': [],
    'blockers': [
        {'text': 'Local AI backend catalog/benchmark APIs not published yet (#12).', 'severity': 'info'},
    ],
    'model_recommendations': [
        {
            'task': 'UI presentation work',
            'model': 'Unavailable — no measured task/model evidence',
            'rationale': 'Fixture only; recommendations require backend evidence.',
        },
    ],
    'limitations': [FIXTURE_BANNER],
    'detail': 'Synthetic agent center payload for UI layout checks.',
}


def _cell(value):
    if value is None or value == '':
        return 'Unavailable'
    return str(value)


def _is_fixture(payload):
    return (payload or {}).get('fixture_kind') == FIXTURE_KIND


def unavailable_inventory(detail=None):
    result = deepcopy(UNAVAILABLE_INVENTORY)
    if detail:
        result['detail'] = detail
    return result


def unavailable_catalog(detail=None):
    result = deepcopy(UNAVAILABLE_CATALOG)
    if detail:
        result['detail'] = detail
    return result


def unavailable_benchmarks(detail=None):
    result = deepcopy(UNAVAILABLE_BENCHMARKS)
    if detail:
        result['detail'] = detail
    return result


def unavailable_agents(detail=None):
    result = deepcopy(UNAVAILABLE_AGENTS)
    if detail:
        result['detail'] = detail
    return result


class AiOptimizerCenter(QWidget):
    """Tabbed AI Optimizer dashboard; reuses host workers and shared status widgets."""

    def __init__(
        self,
        host,
        recommend_provider=None,
        inventory_provider=None,
        catalog_provider=None,
        benchmark_provider=None,
        agent_provider=None,
        parent=None,
    ):
        super().__init__(parent)
        from .ui import label, button, table

        self.label, self.button, self.table = label, button, table
        self.host = host
        self.recommend_provider = recommend_provider
        self.inventory_provider = inventory_provider
        self.catalog_provider = catalog_provider
        self.benchmark_provider = benchmark_provider
        self.agent_provider = agent_provider
        self.closed = False
        self.cancel_token = None
        self._channels = {
            'overview': 'ai-opt-overview',
            'models': 'ai-opt-models',
            'compare': 'ai-opt-compare',
            'agents': 'ai-opt-agents',
            'recommend': 'ai-opt-recommend',
        }
        # channel_key -> last accepted generation / payload (same apply step).
        self._applied_generation = {}
        self._last_payload = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(label('AI Optimizer', 'title'))
        layout.addWidget(label(
            'Providers • models • comparisons • coding agents • recommendations  •  '
            'No downloads, runtime installs, or paid API calls from this view',
            'muted'))
        self.banner = label('', 'muted')
        self.banner.setObjectName('aiOptimizerBanner')
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName('AI Optimizer sections')
        layout.addWidget(self.tabs, 1)

        self._build_overview()
        self._build_models()
        self._build_compare()
        self._build_agents()
        self._build_recommend()

        row = QHBoxLayout()
        self.refresh_all_button = button('Refresh all sections', self.refresh_all, True)
        self.cancel_button = button('Cancel in-flight AI Optimizer work', self.cancel_all)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.refresh_all_button)
        row.addWidget(self.cancel_button)
        row.addStretch(1)
        layout.addLayout(row)

    def set_providers(
        self,
        *,
        recommend_provider=None,
        inventory_provider=None,
        catalog_provider=None,
        benchmark_provider=None,
        agent_provider=None,
    ):
        if recommend_provider is not None:
            self.recommend_provider = recommend_provider
        if inventory_provider is not None:
            self.inventory_provider = inventory_provider
        if catalog_provider is not None:
            self.catalog_provider = catalog_provider
        if benchmark_provider is not None:
            self.benchmark_provider = benchmark_provider
        if agent_provider is not None:
            self.agent_provider = agent_provider

    def _tab(self, title):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(8, 12, 8, 8)
        box.setSpacing(10)
        self.tabs.addTab(page, title)
        return box

    def _build_overview(self):
        box = self._tab('Overview')
        box.addWidget(self.label(
            'Local and cloud providers, runtime availability, utilization, and active workloads. '
            'Utilization uses the existing workstation telemetry sampler when refreshed.',
            'muted'))
        self.overview_badge = StatusBadge('unavailable', 'Overview not refreshed yet')
        box.addWidget(self.overview_badge)
        self.util_table = self.table(['Resource', 'Value', 'Source'])
        box.addWidget(self.util_table)
        self.provider_table = self.table(['Provider', 'Kind', 'Availability', 'Detail'])
        box.addWidget(self.provider_table)
        self.runtime_table = self.table(['Runtime', 'Endpoint', 'Status', 'Detail'])
        box.addWidget(self.runtime_table)
        self.workload_table = self.table(['Workload', 'Model', 'Status', 'Detail'])
        box.addWidget(self.workload_table)
        self.overview_notes = ResultView()
        box.addWidget(self.overview_notes, 1)
        box.addWidget(self.button('Refresh overview', self.refresh_overview, True))
        self._fill_util_unavailable()
        self._show_inventory(unavailable_inventory('Overview not refreshed yet.'))

    def _build_models(self):
        box = self._tab('Model explorer')
        box.addWidget(self.label(
            'Catalog fields come from a provider or a labeled synthetic fixture — never guessed.',
            'muted'))
        self.models_badge = StatusBadge('unavailable', 'Model catalog not loaded')
        box.addWidget(self.models_badge)
        self.models_table = self.table([
            'Model', 'Parameters', 'Quantization', 'Context',
            'Est. RAM', 'Est. VRAM', 'Compatibility', 'Execution',
        ])
        self.models_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.models_table, 1)
        self.models_notes = ResultView()
        box.addWidget(self.models_notes)
        box.addWidget(self.button('Refresh model catalog', self.refresh_models, True))
        self._show_catalog(unavailable_catalog('Model catalog not loaded yet.'))

    def _build_compare(self):
        box = self._tab('Model comparison')
        box.addWidget(self.label(
            'Side-by-side benchmark observations only. Missing metrics show Unavailable — not zero.',
            'muted'))
        self.compare_badge = StatusBadge('unavailable', 'Comparisons not loaded')
        box.addWidget(self.compare_badge)
        self.compare_table = self.table([
            'Model', 'Tokens/s', 'TTFT', 'Memory', 'Accuracy', 'Quality', 'API cost', 'Notes',
        ])
        self.compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.compare_table, 1)
        self.compare_notes = ResultView()
        box.addWidget(self.compare_notes)
        box.addWidget(self.button('Refresh comparisons', self.refresh_compare, True))
        self._show_benchmarks(unavailable_benchmarks('Comparisons not loaded yet.'))

    def _build_agents(self):
        box = self._tab('Coding agents')
        box.addWidget(self.label(
            'Codex, Cursor, and Claude — issues, branches, worktrees, PRs, blockers, and '
            'evidence-based model tips when a status provider exists.',
            'muted'))
        self.agents_badge = StatusBadge('unavailable', 'Agent status not loaded')
        box.addWidget(self.agents_badge)
        self.agents_table = self.table(['Agent', 'Status', 'Detail'])
        box.addWidget(self.agents_table)
        self.agent_issues = self.table(['Issue', 'Title', 'State', 'Agent'])
        box.addWidget(self.agent_issues)
        self.agent_branches = self.table(['Branch', 'Agent'])
        box.addWidget(self.agent_branches)
        self.agent_worktrees = self.table(['Worktree', 'Branch'])
        box.addWidget(self.agent_worktrees)
        self.agent_prs = self.table(['Pull request', 'State', 'Agent'])
        box.addWidget(self.agent_prs)
        self.agent_blockers = self.table(['Blocker', 'Severity'])
        box.addWidget(self.agent_blockers)
        self.agent_models = self.table(['Task', 'Recommended model', 'Rationale'])
        box.addWidget(self.agent_models)
        self.agents_notes = ResultView()
        box.addWidget(self.agents_notes, 1)
        box.addWidget(self.button('Refresh coding agents', self.refresh_agents, True))
        self._show_agents(unavailable_agents('Agent status not loaded yet.'))

    def _build_recommend(self):
        box = self._tab('Recommendations')
        box.addWidget(self.label(
            'Uses optimizer.ai.recommend when present. Explains trade-offs from returned evidence only. '
            'Host changes still require approval elsewhere.',
            'muted'))
        self.recommend_badge = StatusBadge('unavailable', 'Recommendations not requested')
        box.addWidget(self.recommend_badge)
        self.recommend_summary = self.label('No recommendation run yet.', 'muted')
        box.addWidget(self.recommend_summary)
        self.recommend_view = ResultView()
        box.addWidget(self.recommend_view, 1)
        row = QHBoxLayout()
        self.recommend_button = self.button('Request recommendations', self.refresh_recommend, True)
        self.recommend_cancel = self.button('Cancel recommendation request', self.cancel_recommend)
        self.recommend_cancel.setEnabled(False)
        row.addWidget(self.recommend_button)
        row.addWidget(self.recommend_cancel)
        row.addStretch(1)
        box.addLayout(row)
        self._show_recommend(unavailable_result(
            'Recommendations not requested yet. Existing PC and Network tools remain available.'))

    def _fill_util_unavailable(self, sample=None):
        rows = [
            ('CPU utilization', _cell(None if sample is None else sample.get('cpu')),
             'Workstation telemetry' if sample is not None else 'Unavailable'),
            ('GPU utilization', _cell(None if not sample else (sample.get('gpu') or {}).get('utilization')),
             'nvidia-smi via telemetry' if sample and sample.get('gpu') else 'Unavailable'),
            ('RAM utilization', _cell(None if sample is None else sample.get('ram')),
             'Workstation telemetry' if sample is not None else 'Unavailable'),
            (
                'VRAM used / total (MiB)',
                (
                    'Unavailable'
                    if not sample or not sample.get('gpu')
                    else f"{_cell((sample.get('gpu') or {}).get('memory_used'))} / "
                         f"{_cell((sample.get('gpu') or {}).get('memory_total'))}"
                ),
                'nvidia-smi via telemetry' if sample and sample.get('gpu') else 'Unavailable',
            ),
        ]
        self.util_table.setRowCount(len(rows))
        for r, (resource, value, source) in enumerate(rows):
            display = str(value)
            if resource.endswith('utilization') and value != 'Unavailable':
                display = f'{value}%'
            self.util_table.setItem(r, 0, QTableWidgetItem(resource))
            self.util_table.setItem(r, 1, QTableWidgetItem(display))
            self.util_table.setItem(r, 2, QTableWidgetItem(source))

    def _set_rows(self, table, rows, columns):
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(columns):
                table.setItem(r, c, QTableWidgetItem(_cell(row.get(key) if isinstance(row, dict) else row[c])))

    def applied_generation(self, channel_key):
        return self._applied_generation.get(channel_key)

    def last_payload(self, channel_key):
        return self._last_payload.get(channel_key)

    def _fixture_payload(self, channel_key, payload):
        if channel_key == 'overview' and isinstance(payload, dict) and 'inventory' in payload:
            return payload.get('inventory')
        return payload

    def _refresh_fixture_banner(self):
        """Banner reflects currently applied payloads only (same results as tables)."""
        if any(_is_fixture(self._fixture_payload(key, payload)) for key, payload in self._last_payload.items()):
            self.banner.setText(FIXTURE_BANNER)
            self.banner.show()
        else:
            self.banner.hide()
            self.banner.setText('')

    def _show_fixture_state(self, badge, payload, empty_status='unavailable'):
        if _is_fixture(payload):
            badge.set_status('warning', f'Synthetic development fixture · {payload.get("detail") or "fixture"}')
            return
        detail = payload.get('detail') or empty_status
        status = 'ok' if payload.get('providers') or payload.get('models') or payload.get('comparisons') or payload.get('agents') else empty_status
        if payload.get('status') in ('ok', 'unavailable', 'error', 'canceled', 'timeout'):
            status = payload['status']
        badge.set_status(status, detail)

    def _show_inventory(self, payload):
        payload = payload or unavailable_inventory()
        self._show_fixture_state(self.overview_badge, payload)
        providers = payload.get('providers') or []
        self.provider_table.setRowCount(len(providers))
        for r, item in enumerate(providers):
            self.provider_table.setItem(r, 0, QTableWidgetItem(_cell(item.get('name') or item.get('id'))))
            self.provider_table.setItem(r, 1, QTableWidgetItem(_cell(item.get('kind'))))
            self.provider_table.setItem(r, 2, QTableWidgetItem(_cell(item.get('availability'))))
            self.provider_table.setItem(r, 3, QTableWidgetItem(_cell(item.get('detail'))))
        if not providers:
            self.provider_table.setRowCount(1)
            self.provider_table.setItem(0, 0, QTableWidgetItem('Unavailable'))
            self.provider_table.setItem(0, 1, QTableWidgetItem('—'))
            self.provider_table.setItem(0, 2, QTableWidgetItem('unavailable'))
            self.provider_table.setItem(0, 3, QTableWidgetItem(payload.get('detail') or 'No providers'))

        runtimes = payload.get('runtimes') or []
        self.runtime_table.setRowCount(max(1, len(runtimes)))
        if not runtimes:
            for c, text in enumerate(['Unavailable', '—', 'unavailable', payload.get('detail') or 'No runtimes']):
                self.runtime_table.setItem(0, c, QTableWidgetItem(text))
        else:
            for r, item in enumerate(runtimes):
                self.runtime_table.setItem(r, 0, QTableWidgetItem(_cell(item.get('id'))))
                self.runtime_table.setItem(r, 1, QTableWidgetItem(_cell(item.get('endpoint'))))
                self.runtime_table.setItem(r, 2, QTableWidgetItem(_cell(item.get('status'))))
                self.runtime_table.setItem(r, 3, QTableWidgetItem(_cell(item.get('detail'))))

        workloads = payload.get('workloads') or []
        self.workload_table.setRowCount(max(1, len(workloads)))
        if not workloads:
            for c, text in enumerate(['None reported', '—', 'unavailable', 'No active AI workloads were reported.']):
                self.workload_table.setItem(0, c, QTableWidgetItem(text))
        else:
            for r, item in enumerate(workloads):
                self.workload_table.setItem(r, 0, QTableWidgetItem(_cell(item.get('name') or item.get('id'))))
                self.workload_table.setItem(r, 1, QTableWidgetItem(_cell(item.get('model'))))
                self.workload_table.setItem(r, 2, QTableWidgetItem(_cell(item.get('status'))))
                self.workload_table.setItem(r, 3, QTableWidgetItem(_cell(item.get('detail'))))

        self.overview_notes.set_data({
            'detail': payload.get('detail'),
            'limitations': payload.get('limitations') or [],
            'fixture_kind': payload.get('fixture_kind'),
            'providers': providers,
            'runtimes': runtimes,
            'workloads': workloads,
        })
        self._refresh_fixture_banner()

    def _show_catalog(self, payload):
        payload = payload or unavailable_catalog()
        self._show_fixture_state(self.models_badge, payload)
        models = payload.get('models') or []
        self.models_table.setRowCount(max(1, len(models)))
        if not models:
            for c in range(self.models_table.columnCount()):
                self.models_table.setItem(0, c, QTableWidgetItem('Unavailable' if c == 0 else '—'))
            self.models_table.setItem(0, 7, QTableWidgetItem(payload.get('detail') or 'No catalog'))
        else:
            for r, model in enumerate(models):
                values = [
                    model.get('name'), model.get('parameters'), model.get('quantization'),
                    model.get('context_window'), model.get('estimated_ram_gib'),
                    model.get('estimated_vram_gib'), model.get('hardware_compatibility'),
                    model.get('execution'),
                ]
                for c, value in enumerate(values):
                    self.models_table.setItem(r, c, QTableWidgetItem(_cell(value)))
        self.models_notes.set_data({
            'detail': payload.get('detail'),
            'limitations': payload.get('limitations') or [],
            'fixture_kind': payload.get('fixture_kind'),
            'models': models,
        })
        self._refresh_fixture_banner()

    def _show_benchmarks(self, payload):
        payload = payload or unavailable_benchmarks()
        self._show_fixture_state(self.compare_badge, payload)
        rows = payload.get('comparisons') or []
        self.compare_table.setRowCount(max(1, len(rows)))
        if not rows:
            for c in range(self.compare_table.columnCount()):
                self.compare_table.setItem(0, c, QTableWidgetItem('Unavailable' if c == 0 else '—'))
            self.compare_table.setItem(0, 7, QTableWidgetItem(payload.get('detail') or 'No comparisons'))
        else:
            for r, item in enumerate(rows):
                values = [
                    item.get('model'), item.get('tokens_per_second'), item.get('time_to_first_token_ms'),
                    item.get('memory_gib'), item.get('task_accuracy'), item.get('quality_score'),
                    item.get('api_cost'), item.get('notes'),
                ]
                for c, value in enumerate(values):
                    self.compare_table.setItem(r, c, QTableWidgetItem(_cell(value)))
        self.compare_notes.set_data({
            'detail': payload.get('detail'),
            'limitations': payload.get('limitations') or [],
            'fixture_kind': payload.get('fixture_kind'),
            'comparisons': rows,
        })
        self._refresh_fixture_banner()

    def _show_agents(self, payload):
        payload = payload or unavailable_agents()
        self._show_fixture_state(self.agents_badge, payload)
        agents = payload.get('agents') or []
        self.agents_table.setRowCount(max(1, len(agents)))
        if not agents:
            self.agents_table.setItem(0, 0, QTableWidgetItem('Unavailable'))
            self.agents_table.setItem(0, 1, QTableWidgetItem('unavailable'))
            self.agents_table.setItem(0, 2, QTableWidgetItem(payload.get('detail') or ''))
        else:
            for r, item in enumerate(agents):
                self.agents_table.setItem(r, 0, QTableWidgetItem(_cell(item.get('name') or item.get('id'))))
                self.agents_table.setItem(r, 1, QTableWidgetItem(_cell(item.get('status'))))
                self.agents_table.setItem(r, 2, QTableWidgetItem(_cell(item.get('detail'))))

        def fill(table, items, keys):
            items = items or []
            table.setRowCount(max(1, len(items)))
            if not items:
                for c in range(table.columnCount()):
                    table.setItem(0, c, QTableWidgetItem('Unavailable' if c == 0 else '—'))
                return
            for r, item in enumerate(items):
                for c, key in enumerate(keys):
                    table.setItem(r, c, QTableWidgetItem(_cell(item.get(key))))

        fill(self.agent_issues, payload.get('issues'), ['id', 'title', 'state', 'agent'])
        fill(self.agent_branches, payload.get('branches'), ['name', 'agent'])
        fill(self.agent_worktrees, payload.get('worktrees'), ['path', 'branch'])
        fill(self.agent_prs, payload.get('pull_requests'), ['id', 'state', 'agent'])
        fill(self.agent_blockers, payload.get('blockers'), ['text', 'severity'])
        fill(self.agent_models, payload.get('model_recommendations'), ['task', 'model', 'rationale'])
        self.agents_notes.set_data({
            'detail': payload.get('detail'),
            'limitations': payload.get('limitations') or [],
            'fixture_kind': payload.get('fixture_kind'),
        })
        self._refresh_fixture_banner()

    def _show_recommend(self, result):
        result = result or unavailable_result()
        status = result.get('status', 'unavailable')
        source = result.get('source') or 'deterministic'
        model = result.get('model') or 'none'
        detail = result.get('detail') or 'No recommendation detail.'
        if _is_fixture(result):
            self.recommend_badge.set_status('warning', FIXTURE_BANNER)
        else:
            self.recommend_badge.set_status(status, f'Recommendation status: {status}')
        self.recommend_summary.setText(
            f'Model: {model} · source: {source} · {detail}\n'
            'Trade-offs (speed / quality / cost / hardware) are explained only from returned evidence; '
            'missing evidence stays Unavailable.'
        )
        suggestions = result.get('suggestions') or []
        cards = []
        for item in suggestions:
            cards.append({
                'title': item.get('title') or item.get('id'),
                'rationale': item.get('rationale'),
                'risk': item.get('risk'),
                'requires_approval': item.get('requires_approval', True),
                'evidence': item.get('evidence'),
                'source': item.get('source'),
            })
        # Explicit empty recommendation categories when backend did not supply them.
        payload = {
            'status': status,
            'detail': detail,
            'source': source,
            'model': model,
            'best_compatible_local_model': result.get('best_compatible_local_model') or 'Unavailable',
            'best_for_coding': result.get('best_for_coding') or 'Unavailable',
            'best_for_reasoning': result.get('best_for_reasoning') or 'Unavailable',
            'best_for_research': result.get('best_for_research') or 'Unavailable',
            'trade_offs': result.get('trade_offs') or 'Unavailable — no measured trade-off evidence in this result.',
            'suggestions': cards,
            'limitations': result.get('limitations') or [],
            'evidence': result.get('evidence') or {},
            'fixture_kind': result.get('fixture_kind'),
        }
        if not cards:
            payload['note'] = 'No advisory suggestions. PC and Network dashboards remain usable.'
        self.recommend_view.set_data(payload)
        self._refresh_fixture_banner()

    def _run(self, channel_key, work, on_result, busy_widgets=()):
        if self.closed or self.host.closing:
            return None
        channel = self._channels[channel_key]
        generation = self.host.requests.next(channel)
        self.cancel_button.setEnabled(True)
        for widget in busy_widgets:
            widget.setEnabled(False)

        # Connect result/done before pool.start so instantaneous providers cannot
        # emit into a slotless QueuedConnection (the Python 3.14 CI flake).
        job = self.host.launch(work, None, True, channel=None, start=False)

        def finish(expected=generation):
            if self.host.requests.accept(channel, expected):
                for widget in busy_widgets:
                    widget.setEnabled(True)
                if not self.host.jobs:
                    self.cancel_button.setEnabled(False)

        def deliver(result, expected=generation):
            if self.closed or self.host.closing or not self.host.requests.accept(channel, expected):
                return
            self._last_payload[channel_key] = result
            self._applied_generation[channel_key] = expected
            on_result(result)

        job.signals.result.connect(deliver)
        job.signals.error.connect(lambda text, expected=generation: deliver({
            'schema_version': 1,
            'detail': 'AI Optimizer worker failed.',
            'limitations': [text[-500:]],
            'providers': [], 'runtimes': [], 'workloads': [], 'models': [],
            'comparisons': [], 'agents': [], 'status': 'error', 'source': 'deterministic',
            'suggestions': [], 'evidence': {}, 'model': None,
        }, expected))
        job.signals.done.connect(finish)
        self.host.pool.start(job)
        return generation

    def refresh_overview(self):
        provider = self.inventory_provider

        def work(_progress):
            sample = None
            try:
                sample = self.host.telemetry.sample()
            except Exception:
                sample = None
            if provider is None:
                inventory = unavailable_inventory(
                    'No inventory provider configured. Utilization below uses local telemetry only when available.')
            else:
                try:
                    inventory = provider()
                except Exception:
                    inventory = unavailable_inventory('Inventory provider failed.')
                    inventory['limitations'] = list(inventory.get('limitations') or []) + [traceback.format_exc()[-500:]]
            return {'sample': sample, 'inventory': inventory}

        def on_result(payload):
            self._fill_util_unavailable(payload.get('sample'))
            self._show_inventory(payload.get('inventory'))

        self.overview_badge.set_status('loading', 'Refreshing overview off the UI thread…')
        return self._run('overview', work, on_result, (self.refresh_all_button,))

    def refresh_models(self):
        provider = self.catalog_provider

        def work(_progress):
            if provider is None:
                return unavailable_catalog()
            try:
                return provider()
            except Exception:
                result = unavailable_catalog('Catalog provider failed.')
                result['limitations'] = list(result.get('limitations') or []) + [traceback.format_exc()[-500:]]
                return result

        self.models_badge.set_status('loading', 'Loading model catalog…')
        return self._run('models', work, self._show_catalog, (self.refresh_all_button,))

    def refresh_compare(self):
        provider = self.benchmark_provider

        def work(_progress):
            if provider is None:
                return unavailable_benchmarks()
            try:
                return provider()
            except Exception:
                result = unavailable_benchmarks('Benchmark provider failed.')
                result['limitations'] = list(result.get('limitations') or []) + [traceback.format_exc()[-500:]]
                return result

        self.compare_badge.set_status('loading', 'Loading comparisons…')
        return self._run('compare', work, self._show_benchmarks, (self.refresh_all_button,))

    def refresh_agents(self):
        provider = self.agent_provider

        def work(_progress):
            if provider is None:
                return unavailable_agents()
            try:
                return provider()
            except Exception:
                result = unavailable_agents('Agent status provider failed.')
                result['limitations'] = list(result.get('limitations') or []) + [traceback.format_exc()[-500:]]
                return result

        self.agents_badge.set_status('loading', 'Loading coding-agent status…')
        return self._run('agents', work, self._show_agents, (self.refresh_all_button,))

    def refresh_recommend(self):
        if self.closed or self.host.closing:
            return None
        if self.cancel_token:
            self.cancel_token.cancel()
        recommend = resolve_recommend(self.recommend_provider if self.recommend_provider is not None else getattr(self.host, 'ai_provider', None))
        channel = self._channels['recommend']
        generation = self.host.requests.next(channel)
        self.cancel_token = CancelToken()
        self.recommend_button.setEnabled(False)
        self.recommend_cancel.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.recommend_badge.set_status('loading', 'Requesting recommendations…')
        snapshot = {
            'inventory': getattr(self.host, 'hardware', {}) or {},
            'network': getattr(getattr(self.host, 'network_center', None), 'snapshot', {}) or {},
        }
        network_result = getattr(getattr(self.host, 'network_center', None), 'intelligence', None)

        def work(_progress):
            if recommend is None:
                return unavailable_result(
                    'optimizer.ai is not present on this build. No download or paid API call was attempted.')
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
                result['detail'] = 'Recommendation worker failed.'
                result['limitations'] = list(result['limitations']) + [traceback.format_exc()[-500:]]
                return result

        job = self.host.launch(work, None, True, channel=None, start=False)

        def on_result(result, expected=generation):
            if self.closed or self.host.closing or not self.host.requests.accept(channel, expected):
                return
            self._last_payload['recommend'] = result
            self._applied_generation['recommend'] = expected
            self._show_recommend(result)

        def on_done(expected=generation):
            if self.host.requests.accept(channel, expected):
                self.recommend_button.setEnabled(True)
                self.recommend_cancel.setEnabled(False)
                self.cancel_token = None
                if not self.host.jobs:
                    self.cancel_button.setEnabled(False)

        job.signals.result.connect(on_result)
        job.signals.error.connect(lambda text, expected=generation: on_result({
            **SYNTHETIC_AI_RESULTS['error'],
            'detail': 'Recommendation worker failed.',
            'limitations': SYNTHETIC_AI_RESULTS['error']['limitations'] + [text[-500:]],
        }, expected))
        job.signals.done.connect(on_done)
        self.host.pool.start(job)
        return generation

    def refresh_all(self):
        # Kick sections in a fixed order. Each uses its own RequestGate channel so
        # in-flight work can overlap; callers that need strict sequencing should
        # await jobs between calls (see tests).
        self.refresh_overview()
        self.refresh_models()
        self.refresh_compare()
        self.refresh_agents()
        self.refresh_recommend()

    def cancel_recommend(self):
        if self.cancel_token:
            self.cancel_token.cancel()
            self.recommend_badge.set_status('canceled', 'Canceling recommendation request')

    def cancel_all(self):
        self.cancel_recommend()
        for channel in self._channels.values():
            self.host.requests.invalidate(channel)

    def stop(self):
        self.closed = True
        self.cancel_all()
