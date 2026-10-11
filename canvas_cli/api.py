"""HTTP client for the Canvas REST API.

Responsibilities:
- Attach the Bearer token only to requests for the configured Canvas host.
- Apply timeouts, retry transient failures, and back off when rate limited.
- Follow Canvas pagination (Link headers).
- Turn every failure into a CanvasError with a redacted, actionable message.
"""

import os
import random
import re
import tempfile
import time
from urllib.parse import urljoin, urlparse

import requests

from . import __version__, config
from .errors import AuthError, CanvasError, RateLimitError

TIMEOUT = (10, 60)  # (connect, read) seconds
MAX_RETRIES = 4
MAX_BACKOFF = 60
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS"}
RETRYABLE_STATUS = {500, 502, 503, 504}

# Indirection so tests can skip real sleeping.
_sleep = time.sleep

_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[^\s\"',]+"),
    re.compile(r"(?i)(access_token=)[^&\s\"']+"),
]


def redact(text, secrets=()):
    """Remove known secrets and token-shaped values from text shown to the user."""
    text = str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


class CanvasClient:
    def __init__(self, base_url=None, token=None, session=None):
        self.base_url = base_url or config.get_url()
        self._token = token
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = f"canvas-term/{__version__}"

    # --- auth ---

    @property
    def token(self):
        if self._token is None:
            self._token = config.get_token()
        if not self._token:
            raise AuthError("No API token configured. Run 'canvas-term config' first.")
        return self._token

    def is_canvas_url(self, url):
        """True if url points at the configured Canvas host over https."""
        target = urlparse(url)
        base = urlparse(self.base_url)
        return target.scheme == "https" and target.netloc.lower() == base.netloc.lower()

    def _redact(self, text):
        return redact(text, [self._token] if self._token else [])

    # --- core request loop ---

    def request(self, method, endpoint, *, retry=None, **kwargs):
        """Send a request and return the response, or raise CanvasError.

        `endpoint` may be an API path ("/api/v1/...") or an absolute URL. The
        token is attached only when the URL belongs to the Canvas host.

        Network errors and 5xx responses are retried only for idempotent
        methods (override with `retry`), so a POST is never sent twice.
        Rate-limited requests are always retried, because Canvas rejects them
        before doing any work.
        """
        method = method.upper()
        url = (
            urljoin(self.base_url + "/", endpoint.lstrip("/"))
            if "://" not in endpoint
            else endpoint
        )
        retry = method in IDEMPOTENT_METHODS if retry is None else retry

        headers = dict(kwargs.pop("headers", None) or {})
        if self.is_canvas_url(url):
            headers["Authorization"] = f"Bearer {self.token}"
        kwargs.setdefault("timeout", TIMEOUT)
        host = urlparse(url).netloc

        for attempt in range(MAX_RETRIES + 1):
            can_retry = attempt < MAX_RETRIES
            try:
                response = self.session.request(method, url, headers=headers, **kwargs)
            except requests.exceptions.Timeout as e:
                if retry and can_retry:
                    self._backoff(attempt)
                    continue
                raise CanvasError(
                    f"Request to {host} timed out. Canvas may be slow or unreachable; try again."
                ) from e
            except requests.exceptions.ConnectionError as e:
                if retry and can_retry:
                    self._backoff(attempt)
                    continue
                raise CanvasError(
                    f"Could not connect to {host}. Check your network connection and "
                    "Canvas URL ('canvas-term config')."
                ) from e
            except requests.exceptions.RequestException as e:
                raise CanvasError(f"Network error talking to {host}: {self._redact(e)}") from e

            if self._is_rate_limited(response):
                if can_retry:
                    self._backoff(attempt, response)
                    continue
                raise RateLimitError(
                    "Canvas is rate limiting requests (too many in a short time). "
                    "Wait a minute and try again."
                )

            if response.status_code in RETRYABLE_STATUS and retry and can_retry:
                self._backoff(attempt, response)
                continue

            if response.ok:  # includes 3xx when the caller disables redirects
                return response
            raise self._error_for(response)

        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _is_rate_limited(response):
        # Canvas signals throttling with 403 + "Rate Limit Exceeded"; proxies may send 429.
        if response.status_code == 429:
            return True
        return response.status_code == 403 and "rate limit exceeded" in response.text.lower()

    @staticmethod
    def _backoff(attempt, response=None):
        delay = None
        if response is not None:
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = int(retry_after)
        if delay is None:
            delay = 2**attempt + random.uniform(0, 1)  # noqa: S311 - jitter, not crypto
        _sleep(min(delay, MAX_BACKOFF))

    def _error_for(self, response):
        status = response.status_code
        path = urlparse(response.url or "").path or "request"
        detail = self._redact(_error_detail(response))

        if status == 401:
            return AuthError(
                "Canvas rejected your API token (401 Unauthorized). It may have expired or "
                "been revoked. Generate a new token in Canvas (Account > Settings > "
                "New Access Token) and run 'canvas-term config'."
            )
        if status == 403:
            return CanvasError(f"Permission denied (403) for {path}: {detail}")
        if status == 404:
            return CanvasError(
                f"Not found (404): {path}. Check the course/assignment IDs or your aliases."
            )
        return CanvasError(f"Canvas API error {status} for {path}: {detail}")

    # --- helpers ---

    def get_json(self, endpoint, **kwargs):
        return parse_json(self.request("GET", endpoint, **kwargs))

    def get_all(self, endpoint, params=None):
        """GET every page of a paginated endpoint and return the combined list."""
        params = {"per_page": 100, **(params or {})}
        results = []
        url = endpoint
        while url:
            response = self.request("GET", url, params=params)
            page = parse_json(response)
            if not isinstance(page, list):
                return page
            results.extend(page)

            next_url = response.links.get("next", {}).get("url")
            # The next link already carries the query string; never follow it off-host.
            url = next_url if next_url and self.is_canvas_url(next_url) else None
            params = None
        return results

    def download(self, url, dest_path):
        """Stream a file to dest_path atomically. Auth is sent only to the Canvas host."""
        with self.request("GET", url, stream=True) as response:
            directory = os.path.dirname(dest_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".partial-")
            try:
                with os.fdopen(fd, "wb") as out:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        out.write(chunk)
                os.replace(tmp_path, dest_path)
            except BaseException:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise


def _error_detail(response):
    """Extract a short human-readable message from a Canvas error body."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or response.reason or "").strip()[:200]
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(
                str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errors
            )
        if isinstance(errors, dict):
            return "; ".join(f"{k}: {v}" for k, v in errors.items())
        if body.get("message"):
            return str(body["message"])
    return str(body)[:200]


def parse_json(response):
    try:
        return response.json()
    except ValueError as e:
        raise CanvasError(
            f"Canvas returned an unexpected (non-JSON) response for {urlparse(response.url).path}."
        ) from e


# --- Per-invocation client used by the CLI ---

_client = None


def get_client():
    global _client
    if _client is None:
        _client = CanvasClient()
    return _client


def reset_client():
    global _client
    _client = None
