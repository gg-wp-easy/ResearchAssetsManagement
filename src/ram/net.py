"""HTTP with retries. MOEX ISS is signed by the Russian Trusted Root CA (Ministry of Digital Development, 2026-04),
which the usual certificate stores do not know: it is trusted for moex.com only."""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from importlib import resources

UA = "Mozilla/5.0 (X11; Linux x86_64) research-assets-management"


class NotFound(Exception):
    """The source does not know the instrument (or answered with nothing)."""


@lru_cache(maxsize=1)
def _moex_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    pem = resources.files("ram").joinpath("certs/russian_trusted_root_ca.pem").read_text()
    ctx.load_verify_locations(cadata=pem)
    return ctx


def fetch(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 60, tries: int = 4) -> bytes:
    host = urllib.parse.urlparse(url).hostname or ""
    ctx = _moex_context() if host.endswith("moex.com") else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ctx) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise NotFound(url) from e
            if e.code in (400, 401, 403) or attempt == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == tries - 1:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_json(url: str, **kw) -> dict:
    return json.loads(fetch(url, **kw))
