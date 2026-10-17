"""Public-host-only, HTTPS, byte-bounded fetches. No retries or partial results."""

from __future__ import annotations

import gzip
import http.client
import io
import ipaddress
import socket
import urllib.error
import urllib.request
import zlib
from urllib.parse import urlsplit

from .extraction import MAX_XML_BYTES, extract_snapshot

DEFAULT_HOSTS = ("www.ecfr.gov", "ecfr.gov", "www.govinfo.gov", "govinfo.gov")


class FetchError(ValueError):
    """Fetch failed; callers must not substitute an empty source document."""


def _check_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.port not in (None, 443)):
        raise FetchError("only credential-free HTTPS URLs on port 443 are accepted")
    host = parsed.hostname.lower()
    if host not in {value.lower() for value in allowed_hosts}:
        raise FetchError("source host is not allowlisted")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise FetchError("source host must resolve exclusively to public IP addresses")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...]):
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url: str, *, timeout: float = 30, max_bytes: int = MAX_XML_BYTES,
                allowed_hosts: tuple[str, ...] = DEFAULT_HOSTS) -> bytes:
    """Return complete decompressed body; bound both transport and expanded bytes.

    Hosts and redirects are allowlisted and DNS-screened. urllib performs TLS
    verification. This is not a hardened network sandbox against DNS rebinding;
    keep the default government-host allowlist for untrusted callers.
    """
    if not 0 < timeout <= 120 or not 0 < max_bytes <= MAX_XML_BYTES:
        raise FetchError("timeout or byte limit outside supported bounds")
    try:
        _check_url(url, allowed_hosts)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                            _SafeRedirect(allowed_hosts))
        request = urllib.request.Request(url, headers={
            "Accept": "application/xml,text/xml", "Accept-Encoding": "gzip",
            "User-Agent": "CitedChangeAnalyzer/0.1 (+local research tool)"})
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise FetchError(f"HTTP status {response.status}; complete snapshot required")
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise FetchError("response exceeds transport byte limit")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FetchError("response exceeds transport byte limit")
            if length and len(body) != int(length):
                raise FetchError("truncated response body")
            encoding = response.headers.get("Content-Encoding", "").lower().strip()
            if encoding not in {"", "identity", "gzip"}:
                raise FetchError("unsupported content encoding")
            if encoding == "gzip" or body.startswith(b"\x1f\x8b"):
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as compressed:
                    body = compressed.read(max_bytes + 1)
            if not body or len(body) > max_bytes:
                raise FetchError("empty body or expanded byte limit exceeded")
            return body
    except FetchError:
        raise
    except (OSError, ValueError, EOFError, urllib.error.URLError,
            http.client.HTTPException, zlib.error) as error:
        raise FetchError(f"snapshot fetch failed: {error}") from error


def fetch_snapshot(url: str, *, date: str, **options) -> dict:
    return extract_snapshot(fetch_bytes(url, **options), date=date, url=url)
