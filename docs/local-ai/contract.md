# Local AI advisory engine — public contract (schema_version 1)

Status: published for issue #12. Consumers (UI, scripts) depend on this document, not on
module internals. Anything not described here is private and may change.

## Entrypoint

```python
from optimizer.ai import recommend

result = recommend(snapshot, network_result=None, *, cancel=None)
```

`recommend` is **synchronous and bounded**. It blocks the calling thread for at most
`connect_timeout_seconds + timeout_seconds` (default 2 s + 30 s) plus a few milliseconds of
local work. It never touches the GUI thread on its own; the UI must run it in its own worker
and pass a `cancel` object.

Optional keyword-only seams, outside the stable contract but supported:
`config=AiConfig(...)` to override limits, `runtime=<object with .generate(prompt, is_canceled)>`
to inject a fake runtime in tests. Callers that omit both get the documented defaults.

### `snapshot`

A JSON-serializable `dict`. The engine **allowlists** the fields it understands and ignores
everything else, so passing a larger envelope is safe. Recognized shapes:

| Source | Accepted at |
| --- | --- |
| `optimizer.windows.inventory()` | `snapshot['inventory']` or merged at the top level |
| `optimizer.network.discover()` | `snapshot['network']` or merged at the top level |
| `optimizer.benchmarks` / network benchmark result | `snapshot['benchmark']` |

`snapshot` must be a `dict`. Anything else raises `ValueError`.

### `network_result`

`None`, or the read-only result of the Network Intelligence Engine. Two shapes are accepted:
the `optimizer.diagnostics.analyze()` result itself, or an observation envelope carrying it at
`['diagnostic']`. The engine only reads it; it never mutates or re-publishes the network
contract, and it tolerates unknown extra keys so the network owner can extend their result
without breaking this engine. Anything other than `dict` or `None` raises `ValueError`.

### `cancel`

`None`, a `threading.Event` (anything with `is_set()`), or a zero-argument callable returning a
truthy value to stop. Checked before the connection probe, before the request, and between
response chunks. An HTTP read already in flight is not forcibly aborted; it stays bounded by
`timeout_seconds`. Anything else raises `ValueError`.

## Result

JSON-serializable `dict`:

```python
{
  "schema_version": 1,
  "status": "ok" | "unavailable" | "timeout" | "canceled" | "error",
  "source": "local_llm" | "deterministic",
  "model": "llama3.2:3b",
  "generated_at": "2026-11-24T22:00:00+00:00",
  "detail": "Human-readable, non-sensitive explanation of status.",
  "evidence": {"network.signal_percent": 42, ...},
  "suggestions": [
    {
      "id": "wifi-signal",
      "title": "Compare a wired trial from the same location",
      "rationale": "Reported signal quality is 42%.",
      "evidence": ["network.signal_percent"],
      "risk": "low" | "moderate" | "high",
      "requires_approval": true,
      "source": "local_llm" | "deterministic"
    }
  ],
  "limitations": ["..."]
}
```

- `status` is always one of the five values above. `ok` means a local model answered and its
  output passed strict schema validation.
- `source` describes where `suggestions` came from. On every non-`ok` status the engine
  returns a **clearly labeled deterministic fallback** (`source` = `deterministic`) built only
  from `evidence`, so diagnostics keep working with the runtime absent.
- `evidence` is the redacted, allowlisted evidence actually used. Keys are stable identifiers
  (`system.*`, `network.*`, `diagnostic.*`, `benchmark.*`). Every `suggestions[*].evidence`
  entry is guaranteed to be a key of this mapping; suggestions citing anything else are
  dropped during validation.
- `requires_approval` is forced to `true` on every suggestion, whatever the model returns.
- `suggestions` never contains a command, script, path, or anything else intended for direct
  execution. There is no field a caller could execute. Host changes continue to go through the
  existing approval-gated action allowlist.
- `limitations` always states that advice is heuristic and uncertain.

## Errors

- `ValueError` — malformed **caller** input (bad `snapshot`, `network_result`, `cancel`, or an
  invalid `AiConfig`). Programming errors surface loudly; they are not swallowed.
- Operational problems never raise. Missing runtime, missing model, refused connection,
  redirect, off-host endpoint, oversized or truncated response, invalid JSON, schema
  violation, unsupported model schema version, timeout, cancellation and concurrency
  saturation all return a typed `status` plus the deterministic fallback.
- Two input-shaped conditions are also operational rather than fatal, and both return
  `status="error"` with the deterministic fallback and no model request: a snapshot
  containing none of the recognized evidence (`suggestions` is then empty, because there is
  nothing to explain), and evidence that cannot be expressed within `max_prompt_chars`.
  Before giving up on the second, the engine drops the least informative evidence keys in a
  fixed order (`optimizer.ai.evidence.TRIM_ORDER`) so the prompt stays deterministic; when
  that happens, `evidence` still reports everything collected while the model may only cite
  the keys it was shown, and `limitations` says how many were omitted.

## Privacy and resource bounds

- Loopback only. `AiConfig.endpoint` must be `http://` on `localhost`, `127.0.0.0/8` or `::1`
  with an explicit port, no credentials, path, query or fragment. Redirects are rejected
  outright, and environment proxies are bypassed so no request can leave the host.
- No cloud calls, telemetry, model downloads, installation or model execution. The engine only
  talks to a runtime the user already installed and started themselves.
- The prompt is built by allowlisting numeric and enumerated evidence; identifiers are never
  collected in the first place. A redaction pass then scrubs MAC addresses, GUIDs, IPv4/IPv6
  literals, emails, user profile paths and token-shaped strings from the serialized prompt as
  defense in depth. The same scrubbing applies to any text the engine reports back.
- Bounds (see `AiConfig`): prompt ≤ 12000 characters, response ≤ 65536 bytes read, output
  ≤ 512 tokens, context ≤ 4096 tokens, ≤ 5 suggestions.
- Concurrency: at most **one** in-flight request per process, guarded by a non-blocking
  semaphore. A second concurrent call returns `status="unavailable"` immediately rather than
  queueing, so two UI workers cannot multiply model memory use. Peak additional memory in this
  process is bounded by `max_response_bytes`; the model's own memory belongs to the external
  runtime and is documented in `README.md`.

## Model-facing schema

The model is asked for exactly this JSON object, and output is validated strictly:

```json
{"schema_version": 1, "suggestions": [{"id": "...", "title": "...", "rationale": "...", "evidence": ["..."], "risk": "low"}]}
```

Unknown top-level keys, unknown suggestion keys, a `schema_version` other than `1`, duplicate
or malformed `id`s, over-long strings, unknown evidence references, or command-shaped text all
cause the offending suggestion — or the whole response — to be rejected.

## Versioning

Breaking changes to the result shape increment `schema_version`. Additive, optional keys do
not. Consumers should read `schema_version` and treat an unexpected value as unsupported.
