## Summary
- Adds a dedicated **AI Optimizer** sidebar page with Overview, Model explorer, Model comparison, Coding agents, and Recommendations.
- Presentation-only: injectable providers, Unavailable defaults, and explicitly labeled synthetic development fixtures — no fabricated telemetry, rankings, pricing, or benchmarks.
- Reuses existing workers, `RequestGate`/`CancelToken`, `StatusBadge`, and `ResultView`; keeps PC Overview, Wi-Fi & Network, and Local AI advice intact.

Closes #16

## Behavior
- Overview shows provider/runtime/workload tables plus CPU/GPU/RAM/VRAM from the existing telemetry sampler when refreshed; missing inventory stays Unavailable.
- Model explorer and comparison render provider data or fixtures; null metrics display as Unavailable (not zero).
- Coding agents surface Codex/Cursor/Claude status, issues/branches/worktrees/PRs/blockers only from a status provider.
- Recommendations call `optimizer.ai.recommend` when present (same contract as #12); otherwise Unavailable. No downloads, runtime installs, or paid API calls.

## Validation
- `QT_QPA_PLATFORM=offscreen` `python -m unittest discover -s tests -p test_ai_optimizer_ui.py` → OK
- `python -m unittest discover -s tests -p test_gui.py` → OK (stack count 11, AI Optimizer nav present)
- `python -m pytest tests -q` → **130 passed**

## Decisions / limitations
- Does not edit `optimizer/ai/` (owned by #12). Comment on #12 lists optional additive inventory/catalog/benchmark/agent fields.
- Synthetic fixtures use `fixture_kind=synthetic_development` and a visible banner.
- start-task used `-Offline` after manual PR overlap checks because `gh api .../pulls/*/files` mixes a non-JSON hint into stderr and breaks Workflow JSON parsing.
- Do not merge automatically.

## Test plan
- [ ] Open AI Optimizer; confirm five tabs and Unavailable defaults without backends
- [ ] Confirm Overview / Wi-Fi & Network / Local AI advice still navigate
- [ ] Run `docs/ai-optimizer/run-tests.ps1`
