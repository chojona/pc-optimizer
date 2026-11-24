"""Redaction applied to anything leaving this module towards the model or a log.

Defense in depth. Identifiers are not collected in the first place (see
`evidence.collect`), so this pass should normally find nothing; it exists so that
a future evidence key, a model echo or a runtime error message cannot leak an
identifier into the prompt, the result `detail`, or a caller's log.
"""
import re

# Ordered: longer, more specific shapes first so a MAC is not eaten as a token.
PATTERNS = (
    ('email', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
    ('guid', re.compile(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b')),
    ('mac', re.compile(r'\b[0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5}\b')),
    ('user-path', re.compile(r'(?i)\b[a-z]:\\users\\[^\s"\'\\]+')),
    # Full form, or any compressed form containing '::'. Deliberately does not
    # match clock-shaped text such as 12:30:45, which carries no identifier.
    ('ipv6', re.compile(
        r'(?<![0-9a-fA-F:])(?:'
        r'(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}'
        r'|(?:[0-9a-fA-F]{1,4}:){1,7}:(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?'
        r'|::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?'
        r')(?![0-9a-fA-F:])')),
    ('ipv4', re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')),
    ('token', re.compile(r'\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{24,}\b')),
)


def scrub(text):
    """Replace identifier-shaped substrings in `text` with labelled placeholders."""
    if not isinstance(text, str):
        text = str(text)
    for label, pattern in PATTERNS:
        text = pattern.sub('[redacted-' + label + ']', text)
    return text


def scrub_detail(text, limit=400):
    """Scrub and truncate an operational message before it reaches a caller."""
    cleaned = ' '.join(scrub(text).split())
    return cleaned[:limit - 1] + '…' if len(cleaned) > limit else cleaned
