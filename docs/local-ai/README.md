# Local AI advisory engine

`optimizer.ai` explains measured system and network evidence in words and proposes
reviewable next steps. It is **optional**. Deterministic diagnostics do not depend on it,
and with no runtime installed the engine still answers — with a clearly labelled
deterministic fallback built from the same evidence.

The public API and result shape live in [`contract.md`](contract.md). This file covers the
runtime and model choice, what the engine does and does not do to the host, its resource
bounds, how to verify it by hand, and what is not yet proven.

## What it is not

- It does not change the host. No setting, service, registry value or driver is touched.
  Every suggestion carries `requires_approval: true`, and host changes continue to go
  through the existing approval-gated action allowlist in `optimizer.actions` /
  `optimizer.network.NetworkActions`.
- It returns no commands. There is no field in the result a caller could execute, and
  command-shaped model text is rejected during validation (`optimizer/ai/schema.py`).
- It makes no cloud calls, sends no telemetry, downloads nothing, installs nothing and
  starts no runtime. It talks only to a loopback runtime the user installed and started.
- It is not a diagnosis. Advice is heuristic; `limitations` says so on every result.

## Runtime and model

| Choice | Value | Why |
| --- | --- | --- |
| Runtime | [Ollama](https://ollama.com) HTTP API on `http://127.0.0.1:11434` | Already common on Windows workstations, loopback by default, simple non-streaming JSON API, no Python dependency needed. Ollama is MIT-licensed. |
| Transport | Python standard library `urllib` | Avoids editing `requirements.txt`, which this task does not own, and nothing here needs more than `urllib`. |
| Model | **Not selected by this engine.** `AiConfig.model` defaults to `llama3.2:3b` | The user installs and licenses the model. A ~3B instruct model is the smallest class that reliably emits a constrained JSON object, and fits ~4 GB of additional RAM/VRAM. Llama 3.2 carries the Llama 3.2 Community License; Qwen 2.5 3B Instruct (Apache-2.0) and Mistral 7B Instruct (Apache-2.0) are reasonable alternatives — pass `AiConfig(model=...)`. |

The engine neither pulls nor validates the model. If the configured model is absent, the
runtime answers HTTP 404 and the engine returns `status="unavailable"` with the
deterministic fallback.

**The model choice above is a reasoned default, not a measured one.** No model has been
benchmarked on this evidence schema; see *Open questions* below.

## Privacy

Two layers, in this order:

1. **Allowlist (the real boundary).** `optimizer/ai/evidence.py` collects a fixed set of
   stable keys holding only numbers, booleans and values from closed enumerations. SSIDs,
   BSSIDs, MAC addresses, adapter GUIDs, PnP identifiers, IP addresses, hostnames, file
   paths and user names are *never collected*, so there is nothing to leak downstream.
   Numbers are range-checked; a free-text field such as `diagnostic.fault` is accepted only
   if it matches a short lowercase identifier shape.
2. **Redaction (defense in depth).** `optimizer/ai/privacy.py` scrubs email, GUID, MAC,
   `C:\Users\…`, IPv4, IPv6 and token shapes from the serialized prompt and from any
   operational message reported back. This should find nothing; it exists so a future
   evidence key or a runtime error string cannot leak one.

Loopback is enforced at configuration time: `http://` only, on `localhost`, `127.0.0.0/8`
or `::1`, with an explicit port and no credentials, path, query or fragment. Redirects are
refused, environment proxies are suppressed, and the answering origin is re-checked.

## Resource bounds

| Bound | Default | Config field |
| --- | --- | --- |
| Connect probe | 2 s | `connect_timeout_seconds` |
| Request | 30 s | `timeout_seconds` |
| Prompt | 12 000 characters | `max_prompt_chars` |
| Response read | 65 536 bytes | `max_response_bytes` |
| Output tokens | 512 | `max_output_tokens` |
| Context tokens | 4 096 | `max_context_tokens` |
| Suggestions | 5 | `max_suggestions` |

- **Wall clock.** A call blocks for at most `connect_timeout_seconds + timeout_seconds`
  plus a few milliseconds of local work. It must run on a worker thread, never the GUI
  thread; the UI owner passes a `cancel` object.
- **Memory in this process.** Bounded by `max_response_bytes` for the response plus a
  prompt under `max_prompt_chars`, so well under a megabyte.
- **Memory outside this process.** The model's weights and KV cache belong to the Ollama
  process, not to this one. A 3B model at 4-bit quantization typically needs ~2–4 GB of
  additional RAM or VRAM while loaded, and Ollama keeps a model resident for several
  minutes after a request. This engine does not and cannot bound that; it is the reason
  for the concurrency rule below.
- **Concurrency.** One in-flight request per process, guarded by a non-blocking semaphore.
  A second concurrent caller receives `status="unavailable"` immediately rather than
  queueing, so two UI workers cannot multiply the runtime's memory use or queue behind a
  30-second request.

## Using it from the UI

```python
from optimizer.ai import recommend

# On a worker thread, with a threading.Event the user can set.
result = recommend(snapshot, network_result, cancel=cancel_event)
```

Render `status`, `source`, `suggestions` and `limitations`. Label a `deterministic`
`source` as such: it is correct, but it is not what the model said. Treat `detail` as
display text, never as an instruction. No UI file, network module or shared manifest needs
to change for this to work — the engine depends on nothing the UI owns, and the UI depends
on this document rather than on module internals.

## Manual, opt-in verification plan

Automated tests never contact a runtime. Verifying against a real model is **explicitly
opt-in** and is the user's own action; its absence is a limitation, not a passing test.

1. Install Ollama yourself and pull a model yourself
   (`ollama pull llama3.2:3b`). Neither step is performed by this application.
2. Confirm it is listening on loopback only:
   `Get-NetTCPConnection -LocalPort 11434 -State Listen`.
3. From the repository root, with a real snapshot in hand:

   ```powershell
   python -c "import json; from optimizer import network, windows; from optimizer.ai import recommend; print(json.dumps(recommend({'inventory': windows.inventory(), 'network': network.discover()}), indent=2))"
   ```

4. Record, in the PR or issue: Ollama version, model name and quantization, CPU/GPU and
   RAM/VRAM, the configured limits, observed wall-clock time, peak runtime memory, the
   `status` and `source` returned, and whether the suggestions cited only real evidence.
5. Repeat with the runtime stopped (`ollama stop` / service stopped) and confirm
   `status="unavailable"`, `source="deterministic"`, and that diagnostics are unaffected.

## Open questions and limitations

- **No real-runtime evidence yet.** No model has been run against this engine on any
  hardware. Schema-conformance rates, latency and memory use are unmeasured. No claim of
  accuracy or of a performance improvement is made anywhere in this engine or its result.
- **Small models drift from schemas.** `format: "json"` plus strict validation is expected
  to be enough, but the rejection rate is unknown. The deterministic fallback is what makes
  that acceptable.
- **Evidence enrichment is pinned to the agreed v1 network contract.** The engine reads the
  network result read-only and tolerates unknown extra keys, so the network owner can extend
  their result without breaking it. Final enrichment beyond the keys listed in
  `optimizer/ai/evidence.py` waits for that contract to settle.
- **Prompt injection is contained, not solved.** Snapshot values cannot carry prose into the
  prompt (the allowlist drops anything that is not a number, boolean or enumerated value),
  and model output cannot carry a command into the result (validation rejects it). What
  remains possible is that a model writes *wrong but well-formed* advice; that is why every
  suggestion is advisory and approval-gated.
