Add a deterministic Network Intelligence Engine that explains gateway/external
and Wi-Fi evidence through the agreed v1 contract. Stale, sparse, missing,
provider-error and route-unstable observations remain explicit; ICMP
nonresponse never becomes application packet loss or proof of cause.

Closes #10

- Public API: `optimizer.network_intelligence.analyze(snapshot)`, with strict
  versioned validation and JSON-serializable findings, stable rule IDs, evidence
  references, heuristic confidence, limitations and approval-required advice.
- Pure `from_event(event, as_of=...)` adapts existing diagnostic event payloads;
  existing diagnostics/network/WLAN behavior and all UI files are unchanged.
- Work is bounded by 256 rounds, 512 KiB UTF-8, 16384 nodes and depth 8. Existing
  median/MAD analysis is reused; no performance improvement is claimed.
- Contract approved before implementation and published in
  https://github.com/chojona/pc-optimizer/issues/10#issuecomment-7147014782;
  focused contract commit `9c244a5`. Synthetic fixtures and integration/manual
  validation notes are in `docs/network-intelligence/` for #11 and #12.

Validation on Windows / existing Python 3.14 environment:

- `python -m unittest discover -s tests -p test_network_intelligence.py`: 15 passed.
- Required unittest commands for `test_diagnostics.py` and `test_network.py`:
  zero cases (pytest-style legacy tests; Python 3.14 returns exit 5). These are
  explicitly reported rather than counted as passes.
- `python -m pytest tests -q -p no:cacheprovider --basetemp <unique data directory>
  --junitxml=data/network-intelligence-tests.xml`: 106 passed, including legacy
  diagnostic/network regressions. Unchanged base: 91 passed.
- `python -m compileall -q optimizer main.py scripts`: passed.
- `python -m pip check`: no broken requirements.
- `finish-task.ps1` dry-run and validation-only invocation passed; its reviewed
  `docs/network-intelligence/validate.ps1` propagates test failures.

Tests cover normal/shared/external-only/conflicting/target-specific patterns,
alignment and warm-up, stale filtering, provider errors, nonresponse semantics,
signal freshness, strict malformed/bounded inputs, deterministic serialization,
evidence references, synthetic consumer fixtures, adapter isolation and blocked
socket/process/file operations. Import works with GUI, providers, storage and
AI modules unavailable. No dependencies were installed and no probes or host
settings changes were performed by analysis.

Remaining validation: existing Windows CI matrix (Python 3.12/3.13/3.14 and
source bundle) must pass after publication and before review. Synthetic tests do
not establish a real router/ISP/radio fault. UI wiring belongs to #11 and AI
integration/privacy to #12. Long existing histories exceeding the cap are
rejected, not silently truncated. Caller supplies one route/clock session and
evaluation time; the backend cannot independently verify those identities.

Owner: `codex-20261124-network-01`; branch:
`codex/issue-10-network-intelligence`; base:
`7ceed211eff7ed7459ccb92ff19010fc105fd2da`. Claims are retained through review;
no merge, automatic action or cleanup is requested.
