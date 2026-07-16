from __future__ import annotations

import socket
import unittest
from unittest import mock

from news_extractor import FetchError, SafeHTTPClient, UnsafeUrlError
from news_extractor.article_extractor import (
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _RawResponse,
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


class SafeHTTPClientTests(unittest.TestCase):
    def test_rejects_invalid_schemes_credentials_controls_and_hosts(self) -> None:
        client = SafeHTTPClient(resolver=resolver_for({}))
        for url in (
            "file:///etc/passwd",
            "ftp://example.test/file",
            "https://user:secret@example.test/article",
            "https://example.test/line\nbreak",
            "https:///missing-host",
        ):
            with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                client.fetch(url)

    def test_rejects_private_loopback_link_local_and_mixed_dns_answers(self) -> None:
        mapping = {
            "loopback.test": ["127.0.0.1"],
            "private.test": ["10.20.30.40"],
            "linklocal.test": ["169.254.169.254"],
            "mixed.test": [PUBLIC_IP, "192.168.1.20"],
        }
        client = SafeHTTPClient(resolver=resolver_for(mapping))

        for hostname in mapping:
            with self.subTest(hostname=hostname), self.assertRaises(UnsafeUrlError):
                client.fetch(f"https://{hostname}/article")

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
            create.assert_called_once_with((PUBLIC_IP, 8080), 3, None)

        with mock.patch("socket.create_connection", return_value=raw_socket) as create:
            https_connection = _PinnedHTTPSConnection(
                "public.test",
                PUBLIC_IP,
                443,
                3,
                context,
            )
            https_connection.connect()
            create.assert_called_once_with((PUBLIC_IP, 443), 3, None)
            context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="public.test")

    def test_unicode_paths_and_queries_are_encoded_before_the_request(self) -> None:
        client = SafeHTTPClient(resolver=resolver_for({}))
        target = client._validate_target("https://public.test/İstanbul haber?q=şeker ve çay")

        self.assertEqual(
            target.request_target,
            "/%C4%B0stanbul%20haber?q=%C5%9Feker%20ve%20%C3%A7ay",
        )


if __name__ == "__main__":
    unittest.main()
