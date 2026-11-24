# Synthetic fixtures for UI consumers

These shapes mirror the published contracts from issues #10 and #12. The UI
owns presentation only; backend packages remain optional imports.

## Network intelligence result

See `optimizer.network_ui.SYNTHETIC_INTELLIGENCE` for `empty`, `ok`, and `error`
examples. Required keys: `schema_version`, `summary`, `findings`,
`recommendations`, `limitations`, `evidence`.

## Local AI result

See `optimizer.ai_ui.SYNTHETIC_AI_RESULTS` for `unavailable`, `ok`, `error`, and
`canceled`. Required keys: `schema_version`, `status`, `source`, `model`,
`detail`, `evidence`, `suggestions`, `limitations`.
