# AI Optimizer presentation fixtures

These shapes are for UI tests and labeled development previews. They are **not**
measured results. Every synthetic envelope includes:

```json
"fixture_kind": "synthetic_development",
"limitations": ["Synthetic development fixture — not measured on this machine."]
```

## Inventory

```json
{
  "schema_version": 1,
  "fixture_kind": "synthetic_development",
  "providers": [
    {"id": "ollama-local", "name": "Ollama", "kind": "local", "availability": "unknown"},
    {"id": "cloud-example", "name": "Example cloud API", "kind": "cloud", "availability": "unavailable"}
  ],
  "runtimes": [
    {"id": "ollama", "endpoint": "loopback-only", "status": "unavailable", "detail": "Not probed in this fixture."}
  ],
  "workloads": [],
  "limitations": ["Synthetic development fixture — not measured on this machine."]
}
```

## Catalog / benchmarks / agents

See `SYNTHETIC_*` constants in `optimizer/ai_optimizer_ui.py`. Fields may be
`null` to exercise Unavailable rendering. Comparison metrics must never be
filled with guessed numbers outside an explicitly labeled fixture.
