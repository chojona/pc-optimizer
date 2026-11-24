"""Strict validation of model output.

Model text is untrusted input, exactly like a network response. Nothing here
trusts a field because it looks right: unknown keys, wrong types, over-long
strings, unknown evidence references, duplicate identifiers and command-shaped
text are all rejected. A rejected suggestion is dropped; a rejected envelope
makes the whole response invalid and the engine falls back to deterministic
advice.

Rejecting command-shaped text is belt and braces. The result has no field a
caller could execute, and host changes go through the existing approval-gated
action allowlist, so a generated command has nothing to invoke even if it
survives. It is rejected anyway so that a model cannot use `rationale` as a
channel for instructions aimed at whoever reads the panel.
"""
import re

MAX_TITLE = 120
MAX_RATIONALE = 600
MAX_EVIDENCE_REFS = 6

ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{1,39}$')
ENVELOPE_KEYS = frozenset(('schema_version', 'suggestions'))
SUGGESTION_KEYS = frozenset(('id', 'title', 'rationale', 'evidence', 'risk'))
RISKS = ('low', 'moderate', 'high')

#: Shapes that indicate the model is emitting something to run rather than advice.
COMMAND_PATTERNS = (
    re.compile(r'(?i)\b(?:powershell|pwsh|cmd\.exe|regedit|reg\s+(?:add|delete)|netsh|bcdedit|'
               r'diskpart|sc\s+(?:config|stop|start)|schtasks|wmic|rundll32|curl|wget|'
               r'invoke-(?:expression|webrequest|restmethod)|start-process|set-itemproperty|'
               r'new-itemproperty|remove-item|stop-service|set-service|sudo|chmod|rm\s+-rf)\b'),
    re.compile(r'(?i)\.(?:exe|ps1|bat|cmd|vbs|msi|scr|dll|sh)\b'),
    re.compile(r'(?i)\b[a-z]:\\'),
    re.compile(r'(?i)\b(?:https?|ftp|file)://'),
    re.compile(r'(?:\|\||&&|\$\(|`|\${|<\?|</)'),
    re.compile(r'(?i)(?:^|\n)\s*(?:\$|>|#!|PS[ >])'),
)


def looks_executable(text):
    """True when `text` contains something shaped like a command, path or URL."""
    return any(pattern.search(text) for pattern in COMMAND_PATTERNS)


def _text(value, limit):
    if not isinstance(value, str):
        return None
    cleaned = ' '.join(value.split())
    if not 1 <= len(cleaned) <= limit or looks_executable(cleaned):
        return None
    return cleaned


def _suggestion(raw, allowed_evidence, seen):
    if not isinstance(raw, dict) or set(raw) != SUGGESTION_KEYS:
        return None, 'suggestion must carry exactly id, title, rationale, evidence and risk'
    identifier = raw['id']
    if not isinstance(identifier, str) or not ID_PATTERN.match(identifier):
        return None, 'suggestion id must be 2-40 characters of a-z, 0-9 and hyphen'
    if identifier in seen:
        return None, f'duplicate suggestion id {identifier!r}'
    title = _text(raw['title'], MAX_TITLE)
    if not title:
        return None, f'{identifier}: title is empty, over-long or command-shaped'
    rationale = _text(raw['rationale'], MAX_RATIONALE)
    if not rationale:
        return None, f'{identifier}: rationale is empty, over-long or command-shaped'
    references = raw['evidence']
    if not isinstance(references, list) or not 1 <= len(references) <= MAX_EVIDENCE_REFS:
        return None, f'{identifier}: evidence must list 1-{MAX_EVIDENCE_REFS} keys'
    if any(not isinstance(r, str) for r in references):
        return None, f'{identifier}: evidence must list strings'
    if len(set(references)) != len(references):
        return None, f'{identifier}: evidence repeats a key'
    if any(r not in allowed_evidence for r in references):
        return None, f'{identifier}: cites evidence that was not collected'
    if raw['risk'] not in RISKS:
        return None, f'{identifier}: risk must be one of {", ".join(RISKS)}'
    return dict(id=identifier, title=title, rationale=rationale, evidence=list(references),
                risk=raw['risk'], requires_approval=True, source='local_llm'), None


def validate(payload, allowed_evidence, *, schema_version=1, limit=5):
    """Validate a decoded model response.

    Returns `(suggestions, rejections)`. `suggestions` is empty when the envelope
    itself is invalid; `rejections` holds a human-readable reason per problem, for
    the result `limitations`. Never raises on bad model output.
    """
    if not isinstance(payload, dict):
        return [], ['model response was not a JSON object']
    extra = set(payload) - ENVELOPE_KEYS
    if extra:
        return [], ['model response carried unexpected keys: ' + ', '.join(sorted(extra))]
    declared = payload.get('schema_version')
    # Exact integer only: `1.0` and `True` both compare equal to 1 in Python, and
    # neither is a version this engine agreed to speak.
    if isinstance(declared, bool) or not isinstance(declared, int) or declared != schema_version:
        return [], [f'model response declared unsupported schema_version {declared!r}']
    raw = payload.get('suggestions')
    if not isinstance(raw, list):
        return [], ['model response did not carry a list of suggestions']
    if len(raw) > limit:
        return [], [f'model returned {len(raw)} suggestions; the limit is {limit}']
    suggestions, rejections, seen = [], [], set()
    for item in raw:
        parsed, reason = _suggestion(item, allowed_evidence, seen)
        if parsed is None:
            rejections.append('dropped a suggestion: ' + reason)
            continue
        seen.add(parsed['id'])
        suggestions.append(parsed)
    return suggestions, rejections
