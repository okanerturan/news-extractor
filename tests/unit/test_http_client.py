from __future__ import annotations

from contextlib import contextmanager
import socket
import threading
import time
import unittest
from unittest import mock

from news_extractor import FetchError, SafeHTTPClient, UnsafeUrlError
from news_extractor.article_extractor import (
    _DNS_WORKER_LIMIT,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _RawResponse,
    _safe_url_for_log,
)


PUBLIC_IP = "93.184.216.34"


def resolver_for(mapping: dict[str, list[str]]):
    def resolve(host: str, port: int, **_: object):
        return [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in mapping.get(host, [PUBLIC_IP])
        ]

    return resolve


def html_response(body: bytes = b"<html><article><p>safe</p></article></html>") -> _RawResponse:
    return _RawResponse(200, "OK", {"content-type": "text/html; charset=utf-8"}, body)


@contextmanager
def scripted_http_peer(chunks: list[tuple[float, bytes]]):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        try:
            connection, _ = listener.accept()
        except OSError:
            return
        with connection:
            connection.settimeout(1)
            request = bytearray()
            try:
                while b"\r\n\r\n" not in request and len(request) < 64 * 1024:
                    data = connection.recv(4096)
                    if not data:
                        return
                    request.extend(data)
                for delay, payload in chunks:
                    if delay:
                        time.sleep(delay)
                    connection.sendall(payload)
            except OSError:
                return

    thread = threading.Thread(target=serve, name="scripted-http-peer", daemon=True)
    thread.start()
    try:
        yield port
    finally:
        listener.close()
        thread.join(timeout=1)


class SafeHTTPClientTests(unittest.TestCase):
    def test_safe_url_for_log_is_total_and_removes_sensitive_components(self) -> None:
        raw = "https://alice:super-secret@example.test/path?token=top-secret#private"
        self.assertEqual(_safe_url_for_log(raw), "https://example.test/path")
        self.assertEqual(_safe_url_for_log("\x1b[31mnot a URL\x1b[0m"), "<invalid-url>")

        class BrokenString:
            def __str__(self) -> str:
                raise RuntimeError("do not stringify")

        self.assertEqual(_safe_url_for_log(BrokenString()), "<invalid-url>")

    def test_rejects_invalid_schemes_credentials_controls_and_hosts(self) -> None:
        client = SafeHTTPClient(resolver=resolver_for({}))
        for url in (
            "file:///etc/passwd",
            "ftp://example.test/file",
            "https://user:secret@example.test/article",
            "https://example.test/line\nbreak",
            "https:///missing-host",
            "https://example.test:0/article",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                client.fetch(url)

    def test_rejects_private_loopback_link_local_and_mixed_dns_answers(self) -> None:
        mapping = {
            "loopback.test": ["127.0.0.1"],
            "private.test": ["10.20.30.40"],
            "linklocal.test": ["169.254.169.254"],
            "mixed.test": [PUBLIC_IP, "192.168.1.20"],
            "special-v4.test": ["192.0.0.8"],
            "site-local-v6.test": ["fec0::1"],
            "reserved-v6.test": ["400::1"],
            "local-nat64.test": ["64:ff9b:1::"],
            "six-to-four.test": ["2002::"],
            "mapped-private.test": ["::ffff:127.0.0.1"],
            "nat64-private.test": ["64:ff9b::a00:1"],
            "isatap-private.test": ["2606:4700:4700:0:0:5efe:0a00:0001"],
            "isatap-u-bit-private.test": ["2606:4700:4700:0:200:5efe:0a00:0001"],
        }
        client = SafeHTTPClient(resolver=resolver_for(mapping))

        for hostname in mapping:
            with self.subTest(hostname=hostname), self.assertRaises(UnsafeUrlError):
                client.fetch(f"https://{hostname}/article")

    def test_explicit_public_address_exceptions_and_true_public_ips_are_allowed(self) -> None:
        mapping = {
            "pcp-anycast.test": ["192.0.0.9"],
            "turn-anycast.test": ["192.0.0.10"],
            "public-v4.test": [PUBLIC_IP],
            "public-v6.test": ["2606:2800:220:1:248:1893:25c8:1946"],
            "isatap-public.test": ["2606:4700:4700:0:0:5efe:5db8:d822"],
            "isatap-u-bit-public.test": ["2606:4700:4700:0:200:5efe:5db8:d822"],
        }
        client = SafeHTTPClient(resolver=resolver_for(mapping))
        with mock.patch.object(client, "_request_once", return_value=html_response()) as request:
            for hostname in mapping:
                with self.subTest(hostname=hostname):
                    document = client.fetch(f"https://{hostname}/article")
                    self.assertEqual(document.final_url, f"https://{hostname}/article")

        self.assertEqual(request.call_count, len(mapping))

    def test_private_network_access_requires_explicit_opt_in(self) -> None:
        client = SafeHTTPClient(
            allow_private_networks=True,
            resolver=resolver_for({"internal.test": ["10.0.0.7"]}),
        )
        with mock.patch.object(client, "_request_once", return_value=html_response()):
            document = client.fetch("http://internal.test/article")

        self.assertEqual(document.final_url, "http://internal.test/article")

    def test_redirect_destination_is_resolved_and_revalidated_before_request(self) -> None:
        client = SafeHTTPClient(
            resolver=resolver_for({"public.test": [PUBLIC_IP], "internal.test": ["127.0.0.1"]})
        )
        redirect = _RawResponse(302, "Found", {"location": "http://internal.test/secret"}, b"")
        with mock.patch.object(client, "_request_once", return_value=redirect) as request:
            with self.assertRaises(UnsafeUrlError):
                client.fetch("https://public.test/start")

        self.assertEqual(request.call_count, 1)

    def test_https_redirect_cannot_downgrade_to_http(self) -> None:
        client = SafeHTTPClient(resolver=resolver_for({}))
        redirect = _RawResponse(302, "Found", {"location": "http://public.test/article"}, b"")
        with mock.patch.object(client, "_request_once", return_value=redirect) as request:
            with self.assertRaisesRegex(UnsafeUrlError, "downgrade"):
                client.fetch("https://public.test/start")

        self.assertEqual(request.call_count, 1)

    def test_relative_redirects_keep_a_bounded_final_url(self) -> None:
        client = SafeHTTPClient(max_redirects=2, resolver=resolver_for({}))
        responses = [
            _RawResponse(301, "Moved", {"location": "/final"}, b""),
            html_response("Türkçe içerik".encode("utf-8")),
        ]
        with mock.patch.object(client, "_request_once", side_effect=responses):
            document = client.fetch("https://public.test/start")

        self.assertEqual(document.final_url, "https://public.test/final")
        self.assertEqual(document.html, "Türkçe içerik")

    def test_redirect_limit_missing_location_and_status_fail_closed(self) -> None:
        client = SafeHTTPClient(max_redirects=0, resolver=resolver_for({}))
        with mock.patch.object(
            client,
            "_request_once",
            return_value=_RawResponse(302, "Found", {"location": "/again"}, b""),
        ):
            with self.assertRaisesRegex(FetchError, "redirect limit"):
                client.fetch("https://public.test/start")

        client = SafeHTTPClient(resolver=resolver_for({}))
        with mock.patch.object(
            client,
            "_request_once",
            return_value=_RawResponse(302, "Found", {}, b""),
        ):
            with self.assertRaisesRegex(FetchError, "Location"):
                client.fetch("https://public.test/start")

        with mock.patch.object(
            client,
            "_request_once",
            return_value=_RawResponse(500, "Error", {"content-type": "text/html"}, b"failure"),
        ):
            with self.assertRaisesRegex(FetchError, "HTTP 500"):
                client.fetch("https://public.test/start")

    def test_content_type_charset_and_byte_limit_are_enforced(self) -> None:
        client = SafeHTTPClient(max_response_bytes=8, resolver=resolver_for({}))
        with mock.patch.object(client, "_request_once", return_value=html_response(b"123456789")):
            with self.assertRaisesRegex(FetchError, "byte limit"):
                client.fetch("https://public.test/article")

        with mock.patch.object(
            client,
            "_request_once",
            return_value=_RawResponse(200, "OK", {"content-type": "application/pdf"}, b"pdf"),
        ):
            with self.assertRaisesRegex(FetchError, "Content-Type"):
                client.fetch("https://public.test/article")

        body = "İçerik".encode("iso-8859-9")
        with mock.patch.object(
            client,
            "_request_once",
            return_value=_RawResponse(
                200,
                "OK",
                {"content-type": "text/html; charset=iso-8859-9"},
                body,
            ),
        ):
            self.assertEqual(client.fetch("https://public.test/article").html, "İçerik")

    def test_validated_address_is_retained_for_the_socket_layer(self) -> None:
        client = SafeHTTPClient(
            resolver=resolver_for({"public.test": [PUBLIC_IP, "2606:2800:220:1:248:1893:25c8:1946"]})
        )
        target = client._validate_target("https://public.test:8443/path?q=1")

        self.assertEqual(target.addresses, (PUBLIC_IP, "2606:2800:220:1:248:1893:25c8:1946"))
        self.assertEqual(target.host_header, "public.test:8443")
        self.assertEqual(target.request_target, "/path?q=1")

    def test_connection_classes_use_vetted_ip_but_keep_tls_hostname(self) -> None:
        raw_socket = mock.Mock()
        context = mock.Mock()
        context.wrap_socket.return_value = mock.Mock()

        with mock.patch("socket.create_connection", return_value=raw_socket) as create:
            http_connection = _PinnedHTTPConnection("public.test", PUBLIC_IP, 8080, 3)
            http_connection.connect()
            self.assertEqual(create.call_args.args[0], (PUBLIC_IP, 8080))
            self.assertAlmostEqual(create.call_args.args[1], 3, delta=0.1)
            self.assertIsNone(create.call_args.args[2])

        with mock.patch("socket.create_connection", return_value=raw_socket) as create:
            https_connection = _PinnedHTTPSConnection(
                "public.test",
                PUBLIC_IP,
                443,
                3,
                context,
            )
            https_connection.connect()
            self.assertEqual(create.call_args.args[0], (PUBLIC_IP, 443))
            self.assertAlmostEqual(create.call_args.args[1], 3, delta=0.1)
            self.assertIsNone(create.call_args.args[2])
            context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="public.test")

    def test_unicode_paths_and_queries_are_encoded_before_the_request(self) -> None:
        client = SafeHTTPClient(resolver=resolver_for({}))
        target = client._validate_target("https://public.test/İstanbul haber?q=şeker ve çay")

        self.assertEqual(
            target.request_target,
            "/%C4%B0stanbul%20haber?q=%C5%9Feker%20ve%20%C3%A7ay",
        )

    def test_absolute_timeout_includes_synchronous_dns_resolution(self) -> None:
        def slow_resolver(host: str, port: int, **_: object):
            time.sleep(0.5)
            return resolver_for({})(host, port)

        client = SafeHTTPClient(timeout=0.15, resolver=slow_resolver)
        started = time.monotonic()
        with self.assertRaisesRegex(FetchError, "DNS resolution exceeded the absolute fetch timeout"):
            client.fetch("https://slow-dns.test/article")
        self.assertLess(time.monotonic() - started, 0.4)

    def test_dns_worker_capacity_is_process_wide_and_deadline_bounded(self) -> None:
        release_resolvers = threading.Event()
        all_workers_started = threading.Event()
        active_lock = threading.Lock()
        active_workers = 0
        max_active_workers = 0

        def blocked_resolver(host: str, port: int, **_: object):
            nonlocal active_workers, max_active_workers
            with active_lock:
                active_workers += 1
                max_active_workers = max(max_active_workers, active_workers)
                if active_workers == _DNS_WORKER_LIMIT:
                    all_workers_started.set()
            try:
                release_resolvers.wait(timeout=2)
            finally:
                with active_lock:
                    active_workers -= 1
            return resolver_for({})(host, port)

        clients = [
            SafeHTTPClient(timeout=1, resolver=blocked_resolver)
            for _ in range(_DNS_WORKER_LIMIT)
        ]
        caller_errors: list[BaseException] = []

        def fetch(client: SafeHTTPClient) -> None:
            try:
                client.fetch("https://capacity.test/article")
            except BaseException as exc:
                caller_errors.append(exc)

        callers = [
            threading.Thread(target=fetch, args=(client,), daemon=True)
            for client in clients
        ]
        workers: list[threading.Thread] = []
        with mock.patch.object(
            SafeHTTPClient,
            "_request_once",
            return_value=html_response(),
        ):
            try:
                for caller in callers:
                    caller.start()
                self.assertTrue(all_workers_started.wait(timeout=1))
                workers = [
                    thread
                    for thread in threading.enumerate()
                    if thread.name == "news-extractor-dns-capacity.test"
                ]
                self.assertEqual(len(workers), _DNS_WORKER_LIMIT)

                saturated = SafeHTTPClient(timeout=0.1, resolver=blocked_resolver)
                started = time.monotonic()
                with self.assertRaisesRegex(
                    FetchError,
                    "DNS resolution exceeded the absolute fetch timeout",
                ):
                    saturated.fetch("https://capacity.test/saturated")
                self.assertLess(time.monotonic() - started, 0.3)
                with active_lock:
                    self.assertEqual(active_workers, _DNS_WORKER_LIMIT)
                    self.assertEqual(max_active_workers, _DNS_WORKER_LIMIT)
            finally:
                release_resolvers.set()
                for caller in callers:
                    caller.join(timeout=1)
                for worker in workers:
                    worker.join(timeout=1)

        self.assertFalse(caller_errors)
        self.assertTrue(all(not caller.is_alive() for caller in callers))
        self.assertTrue(all(not worker.is_alive() for worker in workers))

    def test_absolute_timeout_is_shared_across_redirect_resolution(self) -> None:
        def delayed_resolver(host: str, port: int, **_: object):
            time.sleep(0.18)
            return resolver_for({})(host, port)

        client = SafeHTTPClient(timeout=0.3, max_redirects=1, resolver=delayed_resolver)
        redirect = _RawResponse(302, "Found", {"location": "https://second.test/final"}, b"")
        with mock.patch.object(
            client,
            "_request_once",
            side_effect=[redirect, html_response()],
        ) as request:
            with self.assertRaisesRegex(FetchError, "DNS resolution exceeded the absolute fetch timeout"):
                client.fetch("https://first.test/start")

        self.assertEqual(request.call_count, 1)

    def test_absolute_timeout_stops_a_slow_header_drip(self) -> None:
        response = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 0\r\n\r\n"
        chunks = [(0.04, bytes([value])) for value in response]
        with scripted_http_peer(chunks) as port:
            client = SafeHTTPClient(
                timeout=0.2,
                allow_private_networks=True,
                resolver=resolver_for({"slow-header.test": ["127.0.0.1"]}),
            )
            started = time.monotonic()
            with self.assertRaisesRegex(FetchError, "absolute fetch timeout"):
                client.fetch(f"http://slow-header.test:{port}/")
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.6)

    def test_absolute_timeout_stops_a_slow_body_drip(self) -> None:
        headers = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html\r\n"
            b"Content-Length: 20\r\n"
            b"Connection: close\r\n\r\n"
        )
        chunks = [(0, headers)] + [(0.04, b"x") for _ in range(20)]
        with scripted_http_peer(chunks) as port:
            client = SafeHTTPClient(
                timeout=0.2,
                allow_private_networks=True,
                resolver=resolver_for({"slow-body.test": ["127.0.0.1"]}),
            )
            started = time.monotonic()
            with self.assertRaisesRegex(FetchError, "absolute fetch timeout"):
                client.fetch(f"http://slow-body.test:{port}/")
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.6)


if __name__ == "__main__":
    unittest.main()
