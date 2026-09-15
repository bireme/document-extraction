"""Transporte adaptado de external-storage; DNS, sockets y TLS simulados."""

import io
import socket
import ssl
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from pdfsum.adapters import pdf_download as http

PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"
PDF = b"%PDF-1.4\ncontenido\n%%EOF\n"
OK = (
    b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Length: "
    + str(len(PDF)).encode()
    + b"\r\n\r\n"
    + PDF
)


def records(*addresses, port=443):
    return [
        (
            socket.AF_INET6 if ":" in ip else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (ip, port, 0, 0) if ":" in ip else (ip, port),
        )
        for ip in addresses
    ]


def redirect(url):
    return (
        f"HTTP/1.1 302 Found\r\nLocation: {url}\r\nContent-Length: 0\r\n\r\n".encode()
    )


class TestPublicTransport(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.destination = Path(directory.name) / "document.pdf"
        self.resolver = Mock(return_value=records(PUBLIC))
        self.sockets = []
        self.replies = [OK]

        def new_socket(*args):
            sock = Mock()
            sock.makefile.return_value = io.BytesIO(self.replies.pop(0))
            self.sockets.append(sock)
            return sock

        self.tls = Mock(side_effect=lambda context, sock, **kwargs: sock)

        def wrap(context, sock, **kwargs):
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            return self.tls(context, sock, **kwargs)

        for name, value in [
            ("socket.getaddrinfo", self.resolver),
            ("socket.socket", Mock(side_effect=new_socket)),
            (
                "socket.create_connection",
                Mock(side_effect=AssertionError("Segunda resolución")),
            ),
            ("ssl.SSLContext.wrap_socket", wrap),
        ]:
            patcher = patch(name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def download(self, url="https://public.example/document?token=secreto"):
        http.PDFDownloader().download(url, self.destination)
        return self.destination.read_bytes()

    def test_local_and_non_global_destinations(self):
        for host in [
            "127.0.0.1",
            "127.42.0.1",
            "[::1]",
            "localhost",
            "LOCALHOST.",
            "a.localhost",
            "localhost.localdomain",
            "ip6-localhost",
            "ip6-loopback",
            "10.2.3.4",
            "172.16.0.1",
            "172.31.255.254",
            "192.168.1.2",
            "169.254.169.254",
            "[fe80::1]",
            "[fd00::1]",
            "[fc00::1]",
            "0.0.0.0",
            "[::]",
            "224.0.0.1",
            "[ff02::1]",
            "240.0.0.1",
            "100.64.0.1",
            "192.0.2.1",
            "[2001:db8::1]",
            "[::ffff:127.0.0.1]",
            "[fe80::1%25eth0]",
        ]:
            with (
                self.subTest(host=host),
                self.assertRaises(http.DownloadError) as caught,
            ):
                self.download(f"http://{host}/document?token=secreto")
            self.assertNotIn("secreto", str(caught.exception))
        self.resolver.assert_not_called()
        self.assertFalse(self.sockets)
        self.assertFalse(self.destination.exists())

    def test_dns_validates_entire_result_before_connect(self):
        for addresses in [
            ("10.0.0.1",),
            ("::1",),
            ("fd00::1",),
            ("fe80::1",),
            (PUBLIC, "192.168.1.1"),
            ("172.16.0.1", PUBLIC),
            (PUBLIC, "fd00::1"),
            (PUBLIC_V6, "127.0.0.1"),
            ("169.254.1.1",),
            ("0.0.0.0",),
            ("224.0.0.1",),
            (),
        ]:
            self.resolver.return_value = records(*addresses)
            with (
                self.subTest(addresses=addresses),
                self.assertRaises(http.DownloadError),
            ):
                self.download()
        self.assertFalse(self.sockets)

    def test_alternative_ip_notations(self):
        self.resolver.return_value = records("127.0.0.1")
        for host in ["2130706433", "127.1", "0x7f000001"]:
            with self.subTest(host=host), self.assertRaises(http.DownloadError):
                self.download(f"http://{host}/")
        self.assertFalse(self.sockets)

    def test_ip_pinning_host_tls_and_proxy_bypass(self):
        self.resolver.side_effect = [records(PUBLIC), records("127.0.0.1")]
        with patch.dict("os.environ", {"https_proxy": "http://secret@127.0.0.1:80"}):
            self.assertEqual(self.download(), PDF)
        self.resolver.assert_called_once_with(
            "public.example", 443, type=socket.SOCK_STREAM
        )
        self.sockets[0].connect.assert_called_once_with((PUBLIC, 443))
        sent = b"".join(call.args[0] for call in self.sockets[0].sendall.call_args_list)
        self.assertIn(b"Host: public.example\r\n", sent)
        self.assertEqual(
            self.tls.call_args.kwargs, {"server_hostname": "public.example"}
        )

    def test_http_public_ipv6(self):
        self.resolver.return_value = records(PUBLIC_V6, port=80)
        self.assertEqual(self.download(f"http://[{PUBLIC_V6}]/"), PDF)
        self.tls.assert_not_called()
        self.sockets[0].connect.assert_called_once_with((PUBLIC_V6, 80, 0, 0))

    def test_redirect_private_literal(self):
        self.replies[:] = [redirect("http://169.254.169.254/")]
        with self.assertRaises(http.DownloadError):
            self.download()
        self.assertEqual(len(self.sockets), 1)
        self.resolver.assert_called_once()

    def test_redirect_dns_rebinding(self):
        self.replies[:] = [redirect("/next")]
        self.resolver.side_effect = [records(PUBLIC), records("127.0.0.1")]
        with self.assertRaises(http.DownloadError):
            self.download()
        self.assertEqual(len(self.sockets), 1)
        self.assertEqual(self.resolver.call_count, 2)

    def test_public_redirect(self):
        self.replies[:] = [redirect("https://other.example/file"), OK]
        self.resolver.side_effect = [records(PUBLIC), records(PUBLIC_V6)]
        self.assertEqual(self.download(), PDF)
        self.sockets[1].connect.assert_called_once_with((PUBLIC_V6, 443, 0, 0))
        self.assertEqual(self.tls.call_args.kwargs["server_hostname"], "other.example")

    def test_redirect_limit(self):
        self.replies[:] = [redirect(f"/next/{i}") for i in range(30)]
        with self.assertRaises(http.DownloadError):
            self.download()
        self.assertEqual(len(self.sockets), http._HTTPRedirect.max_redirections + 1)

    def test_dns_and_tls_failures_are_safe(self):
        self.resolver.side_effect = OSError("user:password@internal?token=secreto")
        with self.assertRaises(http.DownloadError) as caught:
            self.download()
        self.assertNotIn("secreto", str(caught.exception))
        self.resolver.side_effect = None
        self.tls.side_effect = ssl.SSLCertVerificationError("certificado inválido")
        with self.assertRaises(http.DownloadError):
            self.download()
        self.sockets[0].close.assert_called_once()
        self.sockets[0].sendall.assert_not_called()

    def test_socket_failure_uses_prevalidated_fallback(self):
        self.resolver.return_value = records(PUBLIC, PUBLIC_V6)
        self.replies[:] = [OK, OK]
        factory = socket.socket.side_effect

        def fail_first(*args):
            sock = factory(*args)
            if len(self.sockets) == 1:
                sock.connect.side_effect = OSError("fallo")
            return sock

        socket.socket.side_effect = fail_first
        self.assertIs(http._connect_public(("public.example", 443), 5), self.sockets[1])
        self.resolver.assert_called_once()
        self.sockets[0].close.assert_called_once()
        self.sockets[1].connect.assert_called_once_with((PUBLIC_V6, 443, 0, 0))


class TestDownloadContent(unittest.TestCase):
    def test_content_limits_streaming_and_cleanup(self):
        cases = [
            (b"", {}, 200, 1000),
            (b"html", {}, 200, 1000),
            (PDF, {"Content-Type": "text/html"}, 200, 1000),
            (PDF, {}, 206, 1000),
            (PDF, {}, 404, 1000),
            (PDF, {}, 200, 5),
            (PDF, {"Content-Length": "999"}, 200, 1000),
            (PDF, {"Content-Length": "-1"}, 200, 1000),
            (PDF, {"Content-Length": "no"}, 200, 1000),
            (PDF[:-6], {}, 200, 1000),
        ]
        for content, headers, status, limit in cases:
            with (
                self.subTest(case=(content, headers, status, limit)),
                tempfile.TemporaryDirectory() as td,
            ):
                destination = Path(td) / "doc.pdf"
                response = io.BytesIO(content)
                response.status = status
                response.headers = Message()
                for name, value in headers.items():
                    response.headers[name] = value
                opener = Mock(return_value=response)
                with self.assertRaises(http.DownloadError):
                    http.PDFDownloader(max_bytes=limit, opener=opener).download(
                        "https://public.example/a", destination
                    )
                self.assertFalse(destination.exists())

    def test_timeout_and_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "doc.pdf"
            destination.write_bytes(b"propio")
            opener = Mock(side_effect=TimeoutError("secreto"))
            with self.assertRaises(http.DownloadError):
                http.PDFDownloader(timeout=7, opener=opener).download(
                    "https://public.example/a", destination
                )
            opener.assert_called_once_with("https://public.example/a", timeout=7)
            self.assertEqual(destination.read_bytes(), b"propio")

    def test_invalid_configuration(self):
        for kwargs in [
            {"timeout": 0},
            {"timeout": float("nan")},
            {"timeout": float("inf")},
            {"max_bytes": 0},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                http.PDFDownloader(**kwargs)
