"""Configuration and endpoint validation for the local AI advisory engine.

Every bound the engine honours lives here so callers can see and override them in
one place. Endpoint validation is a trust boundary: it is the reason the engine
cannot talk to anything but a loopback runtime the user started themselves.
"""
from dataclasses import asdict, dataclass
import ipaddress
import urllib.parse

SCHEMA_VERSION = 1

#: Statuses the public result may carry. Operational failures never raise.
STATUSES = ('ok', 'unavailable', 'timeout', 'canceled', 'error')
SOURCES = ('local_llm', 'deterministic')
RISKS = ('low', 'moderate', 'high')


@dataclass(frozen=True)
class AiConfig:
    """Explicit model, transport and size limits. Invalid values raise ValueError."""

    endpoint: str = 'http://127.0.0.1:11434'
    model: str = 'llama3.2:3b'
    connect_timeout_seconds: float = 2.0
    timeout_seconds: float = 30.0
    max_prompt_chars: int = 12000
    max_response_bytes: int = 65536
    max_output_tokens: int = 512
    max_context_tokens: int = 4096
    max_suggestions: int = 5

    def __post_init__(self):
        host, port = validate_endpoint(self.endpoint)
        object.__setattr__(self, 'host', host)
        object.__setattr__(self, 'port', port)
        if not isinstance(self.model, str) or not 1 <= len(self.model) <= 120:
            raise ValueError('Model must be an explicit name of 1-120 characters')
        if not all(c.isalnum() or c in '._:-/' for c in self.model):
            raise ValueError('Model name may only contain alphanumerics and . _ : - /')
        if not 0 < self.connect_timeout_seconds <= 30:
            raise ValueError('Connect timeout must be greater than 0 and at most 30 seconds')
        if not 0 < self.timeout_seconds <= 600:
            raise ValueError('Request timeout must be greater than 0 and at most 600 seconds')
        if not 200 <= self.max_prompt_chars <= 200000:
            raise ValueError('Prompt limit must be 200-200000 characters')
        if not 1024 <= self.max_response_bytes <= 8 * 1024 * 1024:
            raise ValueError('Response limit must be 1024 bytes to 8 MiB')
        if not 16 <= self.max_output_tokens <= 8192:
            raise ValueError('Output token limit must be 16-8192')
        if not 256 <= self.max_context_tokens <= 131072:
            raise ValueError('Context token limit must be 256-131072')
        if not 1 <= self.max_suggestions <= 20:
            raise ValueError('Suggestion limit must be 1-20')

    @property
    def generate_url(self):
        return self.endpoint.rstrip('/') + '/api/generate'

    def payload(self):
        """JSON-serializable view for documentation and diagnostics (no secrets held)."""
        return asdict(self)


def validate_endpoint(endpoint):
    """Return (host, port) for a loopback HTTP endpoint, else raise ValueError.

    Rejects non-HTTP schemes, non-loopback hosts, credentials, and any path,
    query or fragment, so a configuration mistake cannot send evidence off-host.
    """
    if not isinstance(endpoint, str) or not endpoint:
        raise ValueError('Endpoint must be a non-empty string')
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != 'http':
        raise ValueError("Endpoint scheme must be 'http' on a loopback address")
    if parsed.username or parsed.password:
        raise ValueError('Endpoint must not carry credentials')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('Endpoint must be an origin only, with no path, query or fragment')
    host = parsed.hostname
    if not host:
        raise ValueError('Endpoint must name a loopback host')
    if host.lower() != 'localhost':
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError(f'Endpoint host {host!r} is not a loopback address') from None
        if not address.is_loopback:
            raise ValueError(f'Endpoint host {host!r} is not a loopback address')
    try:
        port = parsed.port
    except ValueError:
        raise ValueError('Endpoint port is not a valid number') from None
    if not port:
        raise ValueError('Endpoint must state an explicit port')
    return host, port
