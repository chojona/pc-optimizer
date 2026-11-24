"""Loopback HTTP adapter for an already user-installed runtime (target: Ollama).

Standard library only, deliberately: adding an HTTP client would mean editing a
shared dependency manifest that this task does not own, and nothing here needs
more than `urllib`.

The adapter never installs, downloads or starts anything. It talks to a runtime
the user installed and started themselves, on loopback, with proxies bypassed and
redirects refused, so no request can leave the host. Every failure becomes one of
the typed errors below; the engine maps those to a public status.
"""
import json
import socket
import urllib.error
import urllib.request

from .config import AiConfig
from .privacy import scrub_detail

#: Shared by every request this module makes. Kept short and uninformative.
USER_AGENT = 'PCOptimizer-LocalAI/1'


class AiRuntimeError(Exception):
    """Base class for operational runtime problems. Carries a public status."""

    status = 'error'


class RuntimeUnavailable(AiRuntimeError):
    """Nothing is listening, or the runtime refused the request outright."""

    status = 'unavailable'


class ModelUnavailable(AiRuntimeError):
    """The runtime answered but does not have the configured model."""

    status = 'unavailable'


class RuntimeTimeout(AiRuntimeError):
    status = 'timeout'


class Canceled(AiRuntimeError):
    status = 'canceled'


class ResponseRejected(AiRuntimeError):
    """The response was oversized, truncated, redirected or not valid JSON."""

    status = 'error'


class RuntimeFailure(AiRuntimeError):
    """The runtime reported an error of its own."""

    status = 'error'


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect, so a misconfigured runtime cannot forward us off-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ResponseRejected(f'runtime attempted an HTTP {code} redirect; refused')


def build_opener():
    """An opener with no proxy support and no redirect following."""
    # ProxyHandler({}) disables environment proxies: a proxy would make a
    # loopback URL leave the host, defeating the endpoint validation.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects)


class OllamaRuntime:
    """Adapter for Ollama's `/api/generate`, used in non-streaming JSON mode.

    Documented assumptions: Ollama >= 0.1.30 serves `POST /api/generate` on
    loopback port 11434 and honours `format: "json"`, `stream: false` and the
    `num_predict` / `num_ctx` options. The runtime, the model and its licence are
    the user's; this adapter neither selects nor fetches a model.
    """

    def __init__(self, config=None, opener=None):
        self.config = config or AiConfig()
        self.opener = opener or build_opener()

    def _probe(self):
        """Fail fast and cheaply when no runtime is listening on loopback."""
        try:
            with socket.create_connection((self.config.host, self.config.port),
                                          self.config.connect_timeout_seconds):
                return
        except (socket.timeout, TimeoutError) as exc:
            raise RuntimeUnavailable(
                'no local runtime answered within the connect timeout') from exc
        except OSError as exc:
            raise RuntimeUnavailable(
                'no local runtime is listening on the configured loopback port') from exc

    def _body(self, prompt):
        return json.dumps({
            'model': self.config.model,
            'prompt': prompt,
            'stream': False,
            'format': 'json',
            'options': {
                'temperature': 0,
                'num_predict': self.config.max_output_tokens,
                'num_ctx': self.config.max_context_tokens,
            },
        }).encode('utf-8')

    def _read(self, response, is_canceled):
        """Read at most `max_response_bytes`, checking cancellation between chunks."""
        chunks, total = [], 0
        while True:
            if is_canceled():
                raise Canceled('canceled while reading the runtime response')
            chunk = response.read(16 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > self.config.max_response_bytes:
                raise ResponseRejected(
                    f'runtime response exceeded {self.config.max_response_bytes} bytes')
            chunks.append(chunk)
        return b''.join(chunks)

    def generate(self, prompt, is_canceled=lambda: False):
        """Return the model's raw text for `prompt`, or raise an `AiRuntimeError`."""
        if is_canceled():
            raise Canceled('canceled before contacting the runtime')
        self._probe()
        if is_canceled():
            raise Canceled('canceled before sending the request')
        request = urllib.request.Request(
            self.config.generate_url, data=self._body(prompt), method='POST',
            headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                     'User-Agent': USER_AGENT, 'Connection': 'close'})
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                self._assert_loopback(response)
                raw = self._read(response, is_canceled)
        except AiRuntimeError:
            raise
        except urllib.error.HTTPError as exc:
            detail = self._error_detail(exc)
            if exc.code == 404:
                raise ModelUnavailable(
                    f'runtime does not have model {self.config.model!r} ({detail})') from exc
            raise RuntimeFailure(f'runtime returned HTTP {exc.code} ({detail})') from exc
        except (socket.timeout, TimeoutError) as exc:
            raise RuntimeTimeout(
                f'runtime did not answer within {self.config.timeout_seconds} s') from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise RuntimeTimeout(
                    f'runtime did not answer within {self.config.timeout_seconds} s') from exc
            raise RuntimeUnavailable(
                f'could not reach the local runtime ({scrub_detail(exc.reason, 120)})') from exc
        except OSError as exc:
            raise RuntimeUnavailable(
                f'could not reach the local runtime ({scrub_detail(exc, 120)})') from exc
        return self._text(raw)

    def _assert_loopback(self, response):
        """Belt and braces: confirm the answered URL is still the validated origin."""
        url = getattr(response, 'url', None)
        if url and not url.startswith(self.config.endpoint.rstrip('/') + '/'):
            raise ResponseRejected('runtime answered from an unexpected origin; refused')

    @staticmethod
    def _error_detail(exc):
        try:
            payload = json.loads(exc.read(4096).decode('utf-8', 'replace'))
            return scrub_detail(payload.get('error', ''), 200) or 'no detail'
        except Exception:
            return 'no detail'

    def _text(self, raw):
        if not raw:
            raise ResponseRejected('runtime returned an empty response')
        try:
            envelope = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError as exc:
            raise ResponseRejected('runtime response was not valid JSON') from exc
        if not isinstance(envelope, dict):
            raise ResponseRejected('runtime response was not a JSON object')
        error = envelope.get('error')
        if error:
            text = scrub_detail(error, 200)
            if 'not found' in text.lower() or 'try pulling' in text.lower():
                raise ModelUnavailable(f'runtime does not have model {self.config.model!r} ({text})')
            raise RuntimeFailure(f'runtime reported an error ({text})')
        if envelope.get('done') is False:
            raise ResponseRejected('runtime response was truncated before completion')
        text = envelope.get('response')
        if not isinstance(text, str) or not text.strip():
            raise ResponseRejected('runtime response carried no model output')
        return text
