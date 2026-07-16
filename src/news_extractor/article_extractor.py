"""Dependency-free, SSRF-aware news article extraction.

The network boundary is intentionally part of the library rather than delegated
to a general-purpose HTTP client. Every request and redirect is validated,
resolved addresses are checked before use, and the vetted address is pinned to
the socket to avoid a second DNS lookup at connection time.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import math
import re
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from html import unescape
from html.parser import HTMLParser
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote, urljoin, urlsplit

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


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, connect_ip: str, port: int, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        connect_ip: str,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
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

        for redirect_count in range(self.max_redirects + 1):
            target = self._validate_target(current_url)
            if previous_scheme == "https" and target.scheme != "https":
                raise UnsafeUrlError("HTTPS redirects may not downgrade to HTTP")

            response = self._request_once(target)
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

    def _validate_target(self, url: str) -> _Target:
        if not isinstance(url, str) or not url.strip():
            raise UnsafeUrlError("URL must be a non-empty string")
        if any(ord(character) < 32 or ord(character) == 127 for character in url):
            raise UnsafeUrlError("URL contains control characters")

        try:
            parsed = urlsplit(url)
            port = parsed.port
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

        port = port or (443 if scheme == "https" else 80)
        addresses = self._resolve_addresses(hostname, port)
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

    def _resolve_addresses(self, hostname: str, port: int) -> tuple[str, ...]:
        try:
            answers = self._resolver(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except (OSError, socket.gaierror) as exc:
            raise FetchError(f"unable to resolve hostname: {hostname}") from exc

        addresses: list[str] = []
        for answer in answers:
            raw_address = str(answer[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise UnsafeUrlError("DNS returned an invalid IP address") from exc

            if not self.allow_private_networks and not address.is_global:
                raise UnsafeUrlError(
                    f"hostname resolves to a non-public address: {address.compressed}"
                )
            if address.is_multicast or address.is_unspecified:
                raise UnsafeUrlError(f"hostname resolves to an unusable address: {address}")
            normalized = address.compressed
            if normalized not in addresses:
                addresses.append(normalized)

        if not addresses:
            raise FetchError(f"hostname did not resolve to an address: {hostname}")
        return tuple(addresses)

    def _request_once(self, target: _Target) -> _RawResponse:
        last_error: BaseException | None = None
        for connect_ip in target.addresses:
            try:
                return self._perform_request(target, connect_ip)
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                last_error = exc

        raise FetchError(f"request failed for {target.hostname}: {last_error}") from last_error

    def _perform_request(self, target: _Target, connect_ip: str) -> _RawResponse:
        if target.scheme == "https":
            connection: http.client.HTTPConnection = _PinnedHTTPSConnection(
                target.hostname,
                connect_ip,
                target.port,
                self.timeout,
                self._ssl_context,
            )
        else:
            connection = _PinnedHTTPConnection(
                target.hostname,
                connect_ip,
                target.port,
                self.timeout,
            )

        deadline = time.monotonic() + self.timeout
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
                    raise FetchError("response exceeded configured timeout")
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
            raise FetchError("request exceeded configured timeout") from exc
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
            logger.warning("Article extraction failed for url=%s: %s", url, exc)
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
            logger.debug("HTML parser rejected url=%s: %s", url, exc)
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
            logger.debug("Extracted text too short for url=%s (len=%s)", url, len(text))
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
