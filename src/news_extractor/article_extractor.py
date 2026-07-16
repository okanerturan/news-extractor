"""Dependency-free, SSRF-aware news article extraction.

The network boundary is intentionally part of the library rather than delegated
to a general-purpose HTTP client. Every request and redirect is validated,
resolved addresses are checked before use, and the vetted address is pinned to
the socket to avoid a second DNS lookup at connection time.
"""

from __future__ import annotations

import http.client
import io
import ipaddress
import json
import logging
import math
import queue
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
_ARTICLE_TYPES = {
    "article",
    "newsarticle",
    "analysisnewsarticle",
    "opinionnewsarticle",
    "reportagenewsarticle",
}
_IGNORED_TAGS = {
    "aside",
    "button",
    "canvas",
    "dialog",
    "footer",
    "form",
    "header",
    "iframe",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_WHITESPACE = re.compile(r"\s+")
_ANSI_OSC = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
_ANSI_CSI = re.compile(r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]")
_ANSI_TWO_BYTE = re.compile(r"\x1b[@-_]")
_URL_IN_TEXT = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_DNS_WORKER_LIMIT = 8
_DNS_WORKER_SLOTS = threading.BoundedSemaphore(_DNS_WORKER_LIMIT)

# Keep the outbound-address policy independent of changes to ipaddress.is_global
# between supported Python releases. These are the non-public IPv4 blocks from
# the IANA special-purpose registries, with the two globally reachable anycast
# exceptions inside 192.0.0.0/24 handled explicitly below.
_IPV4_PUBLIC_EXCEPTIONS = frozenset(
    {
        ipaddress.IPv4Address("192.0.0.9"),
        ipaddress.IPv4Address("192.0.0.10"),
    }
)
_IPV4_DENY_NETWORKS = tuple(
    ipaddress.IPv4Network(value)
    for value in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_IPV6_GLOBAL_UNICAST = ipaddress.IPv6Network("2000::/3")
_IPV6_WELL_KNOWN_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_IPV6_DENY_NETWORKS = tuple(
    ipaddress.IPv6Network(value)
    for value in (
        "::/128",
        "::1/128",
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
        "3ffe::/16",
        "3fff::/20",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)


def _embedded_ipv4_addresses(
    address: ipaddress.IPv6Address,
) -> tuple[ipaddress.IPv4Address, ...]:
    """Return IPv4 destinations encoded by recognized transition formats."""

    embedded: list[ipaddress.IPv4Address] = []
    if address.ipv4_mapped is not None:
        embedded.append(address.ipv4_mapped)
    if address.sixtofour is not None:
        embedded.append(address.sixtofour)
    if address.teredo is not None:
        embedded.extend(address.teredo)
    if address in _IPV6_WELL_KNOWN_NAT64:
        embedded.append(ipaddress.IPv4Address(address.packed[-4:]))
    if address.packed[8:12] in {b"\x00\x00\x5e\xfe", b"\x02\x00\x5e\xfe"}:
        embedded.append(ipaddress.IPv4Address(address.packed[-4:]))
    return tuple(dict.fromkeys(embedded))


def _is_allowed_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Apply the repository's explicit, stable public-destination policy."""

    if isinstance(address, ipaddress.IPv4Address):
        if address in _IPV4_PUBLIC_EXCEPTIONS:
            return True
        return not any(address in network for network in _IPV4_DENY_NETWORKS)

    embedded = _embedded_ipv4_addresses(address)
    if any(not _is_allowed_public_address(candidate) for candidate in embedded):
        return False
    if address.ipv4_mapped is not None or address in _IPV6_WELL_KNOWN_NAT64:
        return bool(embedded)
    if any(address in network for network in _IPV6_DENY_NETWORKS):
        return False
    return address in _IPV6_GLOBAL_UNICAST


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise socket.timeout("absolute fetch deadline exceeded")
    return remaining


def _safe_terminal_text(
    value: object,
    *,
    preserve_newlines: bool = False,
    preserve_tabs: bool = False,
) -> str:
    """Return text that cannot inject terminal control sequences."""

    try:
        text = str(value)
    except Exception:
        return "<unprintable>"
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    text = _ANSI_TWO_BYTE.sub("", text)
    cleaned: list[str] = []
    for character in text:
        codepoint = ord(character)
        if character == "\n" and preserve_newlines:
            cleaned.append(character)
        elif character == "\t" and preserve_tabs:
            cleaned.append(character)
        elif codepoint < 32 or 127 <= codepoint <= 159:
            continue
        else:
            cleaned.append(character)
    return "".join(cleaned)


def _safe_url_for_log(value: object) -> str:
    """Redact credentials, query, and fragment from an untrusted URL safely."""

    try:
        raw = _safe_terminal_text(value)
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except Exception:
        return "<invalid-url>"
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname:
        return "<invalid-url>"
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    netloc = display_host if port in {None, default_port} else f"{display_host}:{port}"
    path = _safe_terminal_text(parsed.path or "/")
    return urlunsplit((scheme, netloc, path, "", ""))


def _safe_error_for_log(value: object) -> str:
    """Remove terminal controls and redact any URL-shaped error fragments."""

    text = _safe_terminal_text(value)
    return _URL_IN_TEXT.sub(lambda match: _safe_url_for_log(match.group(0)), text)


class FetchError(RuntimeError):
    """Raised when a remote document cannot be fetched safely."""


class UnsafeUrlError(FetchError):
    """Raised when a URL violates the default outbound request policy."""


@dataclass(frozen=True)
class _Target:
    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str
    addresses: tuple[str, ...]


@dataclass(frozen=True)
class _RawResponse:
    status: int
    reason: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class DownloadedDocument:
    """Decoded HTML plus the final URL after validated redirects."""

    html: str
    final_url: str
    content_type: str


class _DeadlineRawReader(io.RawIOBase):
    """Socket reader that reapplies the shrinking wall-clock budget per recv."""

    def __init__(self, wrapped_socket: _DeadlineSocket, deadline: float) -> None:
        super().__init__()
        self._socket = wrapped_socket
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        if self.closed:
            raise ValueError("read of closed deadline socket")
        return self._socket._recv_into(buffer, self._deadline)

    def fileno(self) -> int:
        return self._socket.fileno()

    def close(self) -> None:
        if not self.closed:
            self._socket._release_file()
        super().close()


class _DeadlineSocket:
    """Minimal socket proxy used by http.client under one absolute deadline."""

    def __init__(self, wrapped_socket: socket.socket, deadline: float) -> None:
        self._socket = wrapped_socket
        self._deadline = deadline
        self._file_references = 0
        self._close_requested = False
        self._reference_lock = threading.Lock()

    def sendall(self, data: bytes, flags: int = 0) -> None:
        self._socket.settimeout(_remaining_seconds(self._deadline))
        self._socket.sendall(data, flags)

    def makefile(
        self,
        mode: str = "r",
        buffering: int | None = None,
        **_: Any,
    ) -> io.BufferedReader | _DeadlineRawReader:
        if mode not in {"r", "rb"}:
            raise ValueError("deadline socket only supports binary reads")
        with self._reference_lock:
            if self._close_requested:
                raise OSError("deadline socket is closed")
            self._file_references += 1
        raw = _DeadlineRawReader(self, self._deadline)
        if buffering == 0:
            return raw
        size = io.DEFAULT_BUFFER_SIZE if buffering in {None, -1} else buffering
        try:
            return io.BufferedReader(raw, size)
        except BaseException:
            raw.close()
            raise

    def settimeout(self, value: float | None) -> None:
        remaining = _remaining_seconds(self._deadline)
        self._socket.settimeout(remaining if value is None else min(value, remaining))

    def gettimeout(self) -> float | None:
        return self._socket.gettimeout()

    def close(self) -> None:
        with self._reference_lock:
            self._close_requested = True
            should_close = self._file_references == 0
        if should_close:
            self._socket.close()

    def _recv_into(self, buffer: Any, deadline: float) -> int:
        self._socket.settimeout(_remaining_seconds(deadline))
        return self._socket.recv_into(buffer)

    def _release_file(self) -> None:
        with self._reference_lock:
            self._file_references -= 1
            should_close = self._close_requested and self._file_references == 0
        if should_close:
            self._socket.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._socket, name)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        connect_ip: str,
        port: int,
        timeout: float,
        deadline: float | None = None,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._connect_ip = connect_ip
        self._deadline = deadline if deadline is not None else time.monotonic() + timeout

    def connect(self) -> None:
        wrapped_socket = socket.create_connection(
            (self._connect_ip, self.port),
            _remaining_seconds(self._deadline),
            self.source_address,
        )
        self.sock = _DeadlineSocket(wrapped_socket, self._deadline)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        connect_ip: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
        deadline: float | None = None,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._connect_ip = connect_ip
        self._deadline = deadline if deadline is not None else time.monotonic() + timeout

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            _remaining_seconds(self._deadline),
            self.source_address,
        )
        try:
            raw_socket.settimeout(_remaining_seconds(self._deadline))
            wrapped_socket = self._context.wrap_socket(raw_socket, server_hostname=self.host)
            self.sock = _DeadlineSocket(wrapped_socket, self._deadline)
        except BaseException:
            raw_socket.close()
            raise


class SafeHTTPClient:
    """Small HTML-only HTTP client with a deny-by-default SSRF policy."""

    def __init__(
        self,
        *,
        timeout: float = 10,
        max_response_bytes: int = 2_000_000,
        max_redirects: int = 5,
        allow_private_networks: bool = False,
        user_agent: str = "news-extractor/0.2 (+https://github.com/okturan/news-extractor)",
        resolver: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be greater than zero")
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")

        self.timeout = float(timeout)
        self.max_response_bytes = int(max_response_bytes)
        self.max_redirects = int(max_redirects)
        self.allow_private_networks = allow_private_networks
        self.user_agent = user_agent
        self._resolver = resolver
        self._ssl_context = ssl.create_default_context()

    def fetch(self, url: str) -> DownloadedDocument:
        current_url = url
        previous_scheme: str | None = None
        deadline = time.monotonic() + self.timeout

        for redirect_count in range(self.max_redirects + 1):
            target = self._validate_target(current_url, deadline=deadline)
            if previous_scheme == "https" and target.scheme != "https":
                raise UnsafeUrlError("HTTPS redirects may not downgrade to HTTP")

            response = self._request_once(target, deadline=deadline)
            if response.status in _REDIRECT_STATUSES:
                if redirect_count >= self.max_redirects:
                    raise FetchError("redirect limit exceeded")
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect response did not include Location")
                previous_scheme = target.scheme
                current_url = urljoin(current_url, location)
                continue

            if not 200 <= response.status < 300:
                raise FetchError(f"HTTP {response.status} {response.reason}".strip())

            if len(response.body) > self.max_response_bytes:
                raise FetchError("response exceeds configured byte limit")

            content_type, charset = self._parse_content_type(response.headers)
            if content_type not in _ALLOWED_CONTENT_TYPES:
                raise FetchError(f"unsupported Content-Type: {content_type or 'missing'}")

            try:
                html = response.body.decode(charset, errors="replace")
            except LookupError as exc:
                raise FetchError(f"unsupported response charset: {charset}") from exc

            return DownloadedDocument(
                html=html,
                final_url=current_url,
                content_type=content_type,
            )

        raise FetchError("redirect limit exceeded")

    def _validate_target(self, url: str, *, deadline: float | None = None) -> _Target:
        if not isinstance(url, str) or not url.strip():
            raise UnsafeUrlError("URL must be a non-empty string")
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise UnsafeUrlError("URL contains control characters")

        try:
            parsed = urlsplit(url)
            explicit_port = parsed.port
        except ValueError as exc:
            raise UnsafeUrlError("URL has an invalid port or host") from exc

        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise UnsafeUrlError("only http and https URLs are supported")
        if parsed.username is not None or parsed.password is not None:
            raise UnsafeUrlError("credential-bearing URLs are not supported")
        if not parsed.hostname:
            raise UnsafeUrlError("URL must include a hostname")

        try:
            hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeUrlError("URL hostname is not valid IDNA") from exc
        if not hostname:
            raise UnsafeUrlError("URL must include a hostname")

        if explicit_port == 0:
            raise UnsafeUrlError("URL port must be between 1 and 65535")
        port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
        addresses = self._resolve_addresses(hostname, port, deadline=deadline)
        path = quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~")
        request_target = f"{path}?{query}" if query else path
        default_port = 443 if scheme == "https" else 80
        display_host = f"[{hostname}]" if ":" in hostname else hostname
        host_header = display_host if port == default_port else f"{display_host}:{port}"

        return _Target(
            scheme=scheme,
            hostname=hostname,
            port=port,
            request_target=request_target,
            host_header=host_header,
            addresses=addresses,
        )

    def _resolve_addresses(
        self,
        hostname: str,
        port: int,
        *,
        deadline: float | None = None,
    ) -> tuple[str, ...]:
        effective_deadline = deadline if deadline is not None else time.monotonic() + self.timeout
        outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

        try:
            slot_acquired = _DNS_WORKER_SLOTS.acquire(
                timeout=_remaining_seconds(effective_deadline)
            )
        except socket.timeout as exc:
            raise FetchError("DNS resolution exceeded the absolute fetch timeout") from exc
        if not slot_acquired:
            raise FetchError("DNS resolution exceeded the absolute fetch timeout")

        def resolve() -> None:
            try:
                try:
                    answers = self._resolver(
                        hostname,
                        port,
                        family=socket.AF_UNSPEC,
                        type=socket.SOCK_STREAM,
                    )
                except Exception as exc:
                    outcome.put((False, exc))
                else:
                    outcome.put((True, answers))
            finally:
                _DNS_WORKER_SLOTS.release()

        worker = threading.Thread(
            target=resolve,
            name=f"news-extractor-dns-{hostname}",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            _DNS_WORKER_SLOTS.release()
            raise FetchError("unable to start DNS resolution worker") from exc
        try:
            succeeded, result = outcome.get(timeout=_remaining_seconds(effective_deadline))
        except queue.Empty as exc:
            raise FetchError("DNS resolution exceeded the absolute fetch timeout") from exc
        except socket.timeout as exc:
            raise FetchError("DNS resolution exceeded the absolute fetch timeout") from exc

        if not succeeded:
            error = result
            if isinstance(error, (OSError, socket.gaierror)):
                raise FetchError(f"unable to resolve hostname: {hostname}") from error
            raise FetchError(f"hostname resolver failed: {hostname}") from error  # type: ignore[arg-type]

        answers = result
        if not isinstance(answers, Sequence):
            raise FetchError(f"hostname resolver returned an invalid result: {hostname}")

        addresses: list[str] = []
        for answer in answers:
            try:
                _remaining_seconds(effective_deadline)
            except socket.timeout as exc:
                raise FetchError("DNS resolution exceeded the absolute fetch timeout") from exc
            raw_address = str(answer[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise UnsafeUrlError("DNS returned an invalid IP address") from exc

            if not self.allow_private_networks and not _is_allowed_public_address(address):
                raise UnsafeUrlError(
                    f"hostname resolves to an address denied by the public-destination policy: {address.compressed}"
                )
            if address.is_multicast or address.is_unspecified:
                raise UnsafeUrlError(f"hostname resolves to an unusable address: {address}")
            normalized = address.compressed
            if normalized not in addresses:
                addresses.append(normalized)

        if not addresses:
            raise FetchError(f"hostname did not resolve to an address: {hostname}")
        return tuple(addresses)

    def _request_once(self, target: _Target, *, deadline: float) -> _RawResponse:
        last_error: BaseException | None = None
        for connect_ip in target.addresses:
            try:
                return self._perform_request(target, connect_ip, deadline=deadline)
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc

        raise FetchError(f"request failed for {target.hostname}: {last_error}") from last_error

    def _perform_request(self, target: _Target, connect_ip: str, *, deadline: float) -> _RawResponse:
        try:
            remaining = _remaining_seconds(deadline)
        except socket.timeout as exc:
            raise FetchError("request exceeded the absolute fetch timeout") from exc
        if target.scheme == "https":
            connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
                target.hostname,
                connect_ip,
                target.port,
                remaining,
                self._ssl_context,
                deadline,
            )
        else:
            connection = _PinnedHTTPConnection(
                target.hostname,
                connect_ip,
                target.port,
                remaining,
                deadline,
            )

        try:
            connection.request(
                "GET",
                target.request_target,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "Host": target.host_header,
                    "User-Agent": self.user_agent,
                },
            )
            response = connection.getresponse()
            headers = {name.lower(): value.strip() for name, value in response.getheaders()}

            if response.status in _REDIRECT_STATUSES:
                return _RawResponse(response.status, response.reason, headers, b"")

            encoding = headers.get("content-encoding", "identity").lower()
            if encoding not in {"", "identity"}:
                raise FetchError(f"unsupported Content-Encoding: {encoding}")

            declared_length = headers.get("content-length")
            if declared_length is not None:
                try:
                    length = int(declared_length)
                except ValueError as exc:
                    raise FetchError("invalid Content-Length header") from exc
                if length < 0 or length > self.max_response_bytes:
                    raise FetchError("response exceeds configured byte limit")

            body = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("response exceeded the absolute fetch timeout")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read(min(64 * 1024, self.max_response_bytes + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise FetchError("response exceeds configured byte limit")

            return _RawResponse(response.status, response.reason, headers, bytes(body))
        except socket.timeout as exc:
            raise FetchError("request exceeded the absolute fetch timeout") from exc
        finally:
            connection.close()

    @staticmethod
    def _parse_content_type(headers: Mapping[str, str]) -> tuple[str, str]:
        raw_value = headers.get("content-type", "")
        message = Message()
        message["content-type"] = raw_value
        content_type = message.get_content_type().lower() if raw_value else ""
        charset = message.get_content_charset() or "utf-8"
        return content_type, charset


@dataclass
class _Block:
    tag: str
    semantic: bool
    parts: list[str]


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, list[str]] = {}
        self.json_ld: list[str] = []
        self.title_parts: list[str] = []
        self.headings: list[str] = []
        self.all_blocks: list[str] = []
        self.semantic_blocks: list[str] = []
        self.semantic_parts: list[str] = []
        self._frames: list[tuple[str, bool, bool]] = []
        self._blocks: list[_Block] = []
        self._ignored_depth = 0
        self._semantic_depth = 0
        self._title_depth = 0
        self._json_ld_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {name.lower(): value or "" for name, value in attrs}

        if tag == "meta":
            key = (
                attributes.get("property")
                or attributes.get("name")
                or attributes.get("itemprop")
                or ""
            ).strip().lower()
            content = _clean_text(attributes.get("content", ""))
            if key and content:
                self.metadata.setdefault(key, []).append(content)

        if tag == "script":
            script_type = attributes.get("type", "").split(";", 1)[0].strip().lower()
            if script_type == "application/ld+json":
                self._json_ld_parts = []

        ignored = tag in _IGNORED_TAGS
        semantic = (
            not ignored
            and self._ignored_depth == 0
            and (tag in {"article", "main"} or attributes.get("role", "").lower() == "main")
        )
        self._frames.append((tag, ignored, semantic))
        if ignored:
            self._ignored_depth += 1
        if semantic:
            self._semantic_depth += 1
        if tag == "title":
            self._title_depth += 1

        if self._ignored_depth == 0 and tag in {"p", "blockquote", "li", "h1"}:
            self._blocks.append(_Block(tag, self._semantic_depth > 0, []))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._json_ld_parts is not None:
            self._json_ld_parts.append(data)
        if self._title_depth:
            self.title_parts.append(data)
        if self._ignored_depth:
            return

        if self._semantic_depth:
            self.semantic_parts.append(data)
        if self._blocks:
            self._blocks[-1].parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._json_ld_parts is not None:
            payload = "".join(self._json_ld_parts).strip()
            if payload:
                self.json_ld.append(payload)
            self._json_ld_parts = None

        if tag in {"p", "blockquote", "li", "h1"}:
            for index in range(len(self._blocks) - 1, -1, -1):
                if self._blocks[index].tag == tag:
                    block = self._blocks.pop(index)
                    text = _clean_text(" ".join(block.parts))
                    if text:
                        if tag == "h1":
                            self.headings.append(text)
                        else:
                            if tag != "li" or block.semantic:
                                self.all_blocks.append(text)
                            if block.semantic:
                                self.semantic_blocks.append(text)
                    break

        while self._frames:
            frame_tag, ignored, semantic = self._frames.pop()
            if ignored:
                self._ignored_depth = max(0, self._ignored_depth - 1)
            if semantic:
                self._semantic_depth = max(0, self._semantic_depth - 1)
            if frame_tag == "title":
                self._title_depth = max(0, self._title_depth - 1)
            if frame_tag == tag:
                break


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _IGNORED_TAGS:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _IGNORED_TAGS:
            self.ignored_depth = max(0, self.ignored_depth - 1)

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if item is not None)
    return _WHITESPACE.sub(" ", unescape(str(value))).strip()


def _strip_markup(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        text = " ".join(str(item) for item in value if item is not None)
    else:
        text = str(value or "")
    if not re.search(r"<[A-Za-z][^>]*>", text):
        return _clean_text(text)
    parser = _PlainTextParser()
    parser.feed(text)
    parser.close()
    return _clean_text(" ".join(parser.parts))


def _dedupe(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _list_value(value: Any, *, split_commas: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return _list_value(value.get("name") or value.get("headline"))
    if isinstance(value, (list, tuple, set)):
        return _dedupe(
            item
            for nested in value
            for item in _list_value(nested, split_commas=split_commas)
        )
    text = _clean_text(value)
    if split_commas:
        return _dedupe(part for part in re.split(r"[,;|]", text))
    return [text] if text else []


def _image_value(value: Any) -> str | None:
    if isinstance(value, str):
        return _clean_text(value) or None
    if isinstance(value, Mapping):
        return _image_value(value.get("url") or value.get("contentUrl"))
    if isinstance(value, (list, tuple)):
        for item in value:
            image = _image_value(item)
            if image:
                return image
    return None


def _iter_dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    stack = [value]
    visited = 0
    while stack and visited < 10_000:
        current = stack.pop()
        visited += 1
        if isinstance(current, Mapping):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _short_type(value: Any) -> set[str]:
    values = value if isinstance(value, list) else [value]
    result: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            continue
        result.add(re.split(r"[/#:]", item)[-1].casefold())
    return result


class ArticleExtractor:
    """Extract structured article data from remote URLs or supplied HTML."""

    def __init__(
        self,
        language: str = "tr",
        min_text_length: int = 100,
        timeout: float = 10,
        max_response_bytes: int = 2_000_000,
        max_redirects: int = 5,
        allow_private_networks: bool = False,
        *,
        http_client: SafeHTTPClient | None = None,
    ) -> None:
        if min_text_length < 1:
            raise ValueError("min_text_length must be greater than zero")
        self.language = language
        self.min_text_length = int(min_text_length)
        self.timeout = float(timeout)
        self.max_response_bytes = int(max_response_bytes)
        self.max_redirects = int(max_redirects)
        self.allow_private_networks = allow_private_networks
        self.http_client = http_client or SafeHTTPClient(
            timeout=timeout,
            max_response_bytes=max_response_bytes,
            max_redirects=max_redirects,
            allow_private_networks=allow_private_networks,
        )

    def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """Download and extract one article, returning ``None`` on failure."""
        try:
            document = self.http_client.fetch(url)
            return self.extract_html(
                document.html,
                url=url,
                final_url=document.final_url,
            )
        except (FetchError, OSError, ValueError) as exc:
            logger.warning(
                "Article extraction failed for url=%s: %s",
                _safe_url_for_log(url),
                _safe_error_for_log(exc),
            )
            return None

    def extract_html(
        self,
        html: str,
        *,
        url: str,
        final_url: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        """Extract from already-downloaded HTML without performing network I/O."""
        if not isinstance(html, str):
            raise TypeError("html must be a string")

        parser = _ArticleHTMLParser()
        try:
            parser.feed(html)
            parser.close()
        except (ValueError, AssertionError, RecursionError) as exc:
            logger.debug(
                "HTML parser rejected url=%s: %s",
                _safe_url_for_log(url),
                _safe_error_for_log(exc),
            )
            return None

        structured = self._best_json_ld(parser.json_ld)
        structured_text = _strip_markup(structured.get("articleBody")) if structured else ""
        method = "json-ld"

        if len(structured_text) >= self.min_text_length:
            text = structured_text
        else:
            method = "semantic-html"
            blocks = parser.semantic_blocks or parser.all_blocks
            blocks = _dedupe(block for block in blocks if len(_clean_text(block)) >= 20)
            text = "\n\n".join(blocks)
            if len(text) < self.min_text_length:
                semantic_text = _clean_text(" ".join(parser.semantic_parts))
                if len(semantic_text) > len(text):
                    text = semantic_text

        if len(text) < self.min_text_length:
            logger.debug(
                "Extracted text too short for url=%s (len=%s)",
                _safe_url_for_log(url),
                len(text),
            )
            return None

        metadata = structured or {}
        title = _clean_text(
            metadata.get("headline")
            or metadata.get("name")
            or self._first_meta(parser, "og:title", "twitter:title")
            or (parser.headings[0] if parser.headings else "")
            or " ".join(parser.title_parts)
        )
        authors = _list_value(metadata.get("author")) or _list_value(
            self._first_meta(parser, "author", "article:author")
        )
        keywords = _list_value(metadata.get("keywords"), split_commas=True) or _list_value(
            self._first_meta(parser, "keywords", "news_keywords"),
            split_commas=True,
        )
        description = _clean_text(
            metadata.get("description")
            or self._first_meta(parser, "og:description", "twitter:description", "description")
        ) or None
        image = _image_value(metadata.get("image")) or self._first_meta(
            parser,
            "og:image",
            "twitter:image",
        )
        resolved_url = final_url or url
        if image:
            image = urljoin(resolved_url, image)
            if urlsplit(image).scheme.lower() not in {"http", "https"}:
                image = None

        date = _clean_text(
            metadata.get("datePublished")
            or metadata.get("dateCreated")
            or self._first_meta(
                parser,
                "article:published_time",
                "datepublished",
                "date",
                "publication_date",
            )
        ) or None
        categories = metadata.get("articleSection") or self._first_meta(
            parser,
            "article:section",
        )
        if isinstance(categories, (list, tuple)):
            categories = _list_value(categories)
        elif categories is not None:
            categories = _clean_text(categories)

        return {
            "url": url,
            "final_url": resolved_url,
            "title": title or None,
            "text": text,
            "authors": authors,
            "date": date,
            "keywords": keywords,
            "description": description,
            "image": image,
            "categories": categories,
            "language": self.language,
            "method": method,
            "text_length": len(text),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _first_meta(parser: _ArticleHTMLParser, *keys: str) -> str | None:
        for key in keys:
            values = parser.metadata.get(key)
            if values:
                return values[0]
        return None

    @staticmethod
    def _best_json_ld(payloads: Iterable[str]) -> Mapping[str, Any] | None:
        candidates: list[Mapping[str, Any]] = []
        for payload in payloads:
            cleaned = payload.strip()
            if cleaned.startswith("<!--"):
                cleaned = cleaned[4:]
            if cleaned.endswith("-->"):
                cleaned = cleaned[:-3]
            try:
                document = json.loads(cleaned)
            except (json.JSONDecodeError, TypeError, RecursionError):
                continue

            for candidate in _iter_dicts(document):
                if _short_type(candidate.get("@type")) & _ARTICLE_TYPES:
                    candidates.append(candidate)

        if not candidates:
            return None

        def score(candidate: Mapping[str, Any]) -> tuple[int, int]:
            body_length = len(_strip_markup(candidate.get("articleBody")))
            metadata_fields = sum(
                bool(candidate.get(key))
                for key in ("headline", "author", "datePublished", "description", "image")
            )
            return body_length, metadata_fields

        return max(candidates, key=score)

    def extract_batch(self, urls: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Extract several URLs sequentially and retain input URL keys."""
        return {url: self.extract(url) for url in urls}

    def get_stats(self, results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
        """Summarize success and extraction-method counts."""
        total = len(results)
        successful = sum(result is not None for result in results.values())
        methods: dict[str, int] = {}
        for result in results.values():
            if result:
                method = str(result["method"])
                methods[method] = methods.get(method, 0) + 1

        return {
            "total": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": (successful / total * 100) if total else 0,
            "methods": methods,
        }


def extract_article(url: str) -> Optional[Dict[str, Any]]:
    """Extract one article using the default safe network policy."""
    return ArticleExtractor().extract(url)


__all__ = [
    "ArticleExtractor",
    "DownloadedDocument",
    "FetchError",
    "SafeHTTPClient",
    "UnsafeUrlError",
    "extract_article",
]
