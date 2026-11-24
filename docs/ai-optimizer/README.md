# AI Optimizer dashboard (presentation)

Owns the dedicated **AI Optimizer** UI in PC Optimizer (`optimizer/ai_optimizer_ui.py`).
Backend runtime, model execution, and advisory generation remain with issue #12
(`docs/local-ai/contract.md`). This package documents presentation fixtures and
unavailable-state rules only.

## Rules

- Never invent telemetry, model rankings, pricing, or benchmark scores.
- When a provider is absent, show **Unavailable** with an explanation.
- Synthetic development fixtures must set `fixture_kind` to
  `synthetic_development` and the UI must show a visible fixture banner.
- Do not download models, install runtimes, or initiate paid API calls from the UI.
- Host changes are never applied from this dashboard.

## Injectable providers (UI tests / future backends)

| Provider | Purpose |
| --- | --- |
| `inventory_provider()` | Local/cloud providers, runtime availability, workloads |
| `catalog_provider()` | Model explorer rows |
| `benchmark_provider()` | Side-by-side comparison observations |
| `agent_provider()` | Codex / Cursor / Claude task status |
| `recommend_provider` | Same shape as `optimizer.ai.recommend` |

Defaults resolve `recommend` via optional `optimizer.ai` import (same as Local AI advice).
Other providers default to unavailable envelopes unless tests inject fixtures.

## Worker scheduling

Section refreshes call `MainWindow.launch(..., start=False)`, connect `result`/`done`
handlers, then `pool.start(job)`. Connecting after `pool.start` can miss instantaneous
provider results under QueuedConnection (observed as a Python 3.14 CI flake where the
compare table stayed Unavailable while the badge remained "Loading").

Accepted results record `applied_generation` and `last_payload` on the same apply step
so the fixture banner always reflects the payloads currently shown in the tables.

## Manual checks

1. Open **AI Optimizer** in the sidebar; PC Overview and Wi-Fi & Network still work.
2. With no backend providers, every section shows Unavailable (not fake scores).
3. Inject synthetic fixtures in tests and confirm the fixture banner text appears.
