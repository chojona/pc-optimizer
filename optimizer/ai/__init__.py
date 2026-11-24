"""Optional local-only LLM advisory engine.

Public surface is deliberately small; see `docs/local-ai/contract.md`. The engine
is advisory only: it never changes the host, never returns anything executable,
and never reaches past loopback. Deterministic diagnostics work with no model
installed, because every failure path returns a labelled deterministic fallback.
"""
from .config import RISKS, SCHEMA_VERSION, SOURCES, STATUSES, AiConfig
from .engine import recommend
from .evidence import LABELS as EVIDENCE_LABELS
from .runtime import (AiRuntimeError, Canceled, ModelUnavailable, OllamaRuntime,
                      ResponseRejected, RuntimeFailure, RuntimeTimeout, RuntimeUnavailable)

__all__ = [
    'AiConfig', 'AiRuntimeError', 'Canceled', 'EVIDENCE_LABELS', 'ModelUnavailable',
    'OllamaRuntime', 'RISKS', 'ResponseRejected', 'RuntimeFailure', 'RuntimeTimeout',
    'RuntimeUnavailable', 'SCHEMA_VERSION', 'SOURCES', 'STATUSES', 'recommend',
]
