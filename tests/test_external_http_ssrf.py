"""SSRF con urllib real y DNS, sockets y TLS simulados; nunca usa la red."""

import io
import socket
import ssl
from unittest.mock import Mock

import pytest

from pdfsum.adapters import external_http as http
from pdfsum.external import ExternalInput

PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"
OK = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 4\r\n\r\nhola"


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


@pytest.fixture(autouse=True)
def network(monkeypatch):
    resolver = Mock(return_value=records(PUBLIC))
    sockets = []
    replies = [OK]

    def new_socket(*args):
        sock = Mock()
        sock.makefile.return_value = io.BytesIO(replies.pop(0))
        sockets.append(sock)
        return sock

    tls = Mock(side_effect=lambda context, sock, **kwargs: sock)

    def wrap(context, sock, **kwargs):
        assert context.check_hostname
        assert context.verify_mode == ssl.CERT_REQUIRED
        return tls(context, sock, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(socket, "socket", Mock(side_effect=new_socket))
    monkeypatch.setattr(
        socket,
        "create_connection",
        Mock(side_effect=AssertionError("Segunda resolución")),
    )
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", wrap)
    return resolver, sockets, replies, tls


def download(tmp_path, url="https://public.example/document?token=secreto"):
    destination = tmp_path / "document.txt"
    http.HTTPMaterializer().materialize(ExternalInput("id", "text", url), destination)
    return destination


@pytest.mark.parametrize(
    "host",
    [
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
    ],
)
def test_literal_and_local_names_rejected(tmp_path, network, host, caplog):
    resolver, sockets, _, _ = network
    with pytest.raises(http.MaterializationError) as caught:
        download(tmp_path, f"http://{host}/document?token=secreto")
    assert not sockets
    resolver.assert_not_called()
    assert "secreto" not in str(caught.value) + caplog.text
    assert host not in str(caught.value) + caplog.text
    assert not (tmp_path / "document.txt").exists()


@pytest.mark.parametrize(
    "addresses",
    [
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
    ],
)
def test_dns_rejects_entire_result_before_socket(tmp_path, network, addresses):
    resolver, sockets, _, _ = network
    resolver.return_value = records(*addresses)
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    resolver.assert_called_once()
    assert not sockets


@pytest.mark.parametrize("host", ["2130706433", "127.1", "0x7f000001"])
def test_alternative_ip_notation_checked_after_resolution(tmp_path, network, host):
    resolver, sockets, _, _ = network
    resolver.return_value = records("127.0.0.1")
    with pytest.raises(http.MaterializationError):
        download(tmp_path, f"http://{host}/")
    assert not sockets


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("addresses", [(PUBLIC,), (PUBLIC_V6,), (PUBLIC, PUBLIC_V6)])
def test_public_download_pins_ip_preserves_host_and_tls(
    tmp_path, network, scheme, addresses
):
    resolver, sockets, _, tls = network
    # Una segunda consulta devolvería una dirección interna.
    port = 443 if scheme == "https" else 80
    resolver.side_effect = [records(*addresses, port=port), records("127.0.0.1")]
    assert (
        download(tmp_path, f"{scheme}://public.example/document").read_text() == "hola"
    )
    resolver.assert_called_once_with(
        "public.example", 443 if scheme == "https" else 80, type=socket.SOCK_STREAM
    )
    sockets[0].connect.assert_called_once_with(records(*addresses, port=port)[0][4])
    sent = b"".join(call.args[0] for call in sockets[0].sendall.call_args_list)
    assert b"Host: public.example\r\n" in sent
    if scheme == "https":
        assert tls.call_args.kwargs == {"server_hostname": "public.example"}
    else:
        tls.assert_not_called()


def redirect(url):
    return (
        f"HTTP/1.1 302 Found\r\nLocation: {url}\r\nContent-Length: 0\r\n\r\n".encode()
    )


@pytest.mark.parametrize(
    "target",
    [
        "http://10.0.0.1/",
        "https://[::1]/",
        "http://localhost/",
        "https://internal.example/",
    ],
)
def test_redirect_blocked_before_target_connection(tmp_path, network, target):
    resolver, sockets, replies, _ = network
    replies[:] = [redirect(target)]
    resolver.side_effect = [records(PUBLIC), records("192.168.1.1")]
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    assert len(sockets) == 1
    assert resolver.call_count == (2 if "internal.example" in target else 1)


def test_public_redirect_uses_new_validated_result(tmp_path, network):
    resolver, sockets, replies, tls = network
    replies[:] = [redirect("https://other.example/file"), OK]
    resolver.side_effect = [records(PUBLIC), records(PUBLIC_V6)]
    assert download(tmp_path).read_text() == "hola"
    assert resolver.call_count == 2
    sockets[1].connect.assert_called_once_with((PUBLIC_V6, 443, 0, 0))
    assert tls.call_args.kwargs["server_hostname"] == "other.example"


def test_same_hostname_redirect_rebinding_is_rejected(tmp_path, network):
    resolver, sockets, replies, _ = network
    replies[:] = [redirect("/next")]
    resolver.side_effect = [records(PUBLIC), records("127.0.0.1")]
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    assert len(sockets) == 1
    assert resolver.call_count == 2


def test_redirect_limit_is_preserved(tmp_path, network):
    resolver, sockets, replies, _ = network
    replies[:] = [redirect(f"/next/{index}") for index in range(30)]
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    assert len(sockets) == http._HTTPRedirect.max_redirections + 1
    assert resolver.call_count == len(sockets)


def test_environment_proxies_are_ignored(tmp_path, network, monkeypatch):
    resolver, _, _, _ = network
    for scheme in ("http", "https", "all"):
        monkeypatch.setenv(f"{scheme}_proxy", "http://user:password@127.0.0.1:8888")
        monkeypatch.setenv(f"{scheme.upper()}_PROXY", "http://127.0.0.1:8888")
    monkeypatch.setenv("no_proxy", "")
    assert download(tmp_path).read_text() == "hola"
    assert resolver.call_args.args[0] == "public.example"


def test_fallback_only_uses_prevalidated_addresses(network):
    resolver, sockets, replies, _ = network
    resolver.side_effect = [records(PUBLIC, PUBLIC_V6), records("127.0.0.1")]
    replies[:] = [OK, OK]
    factory = socket.socket.side_effect

    def fail_first(*args):
        sock = factory(*args)
        if len(sockets) == 1:
            sock.connect.side_effect = OSError("fallo")
        return sock

    socket.socket.side_effect = fail_first
    assert http._connect_public(("public.example", 443), 5) is sockets[1]
    resolver.assert_called_once()
    sockets[0].close.assert_called_once()
    sockets[1].connect.assert_called_once_with((PUBLIC_V6, 443, 0, 0))


def test_dns_errors_are_sanitized(tmp_path, network, caplog):
    resolver, sockets, _, _ = network
    resolver.side_effect = OSError("user:password@internal.example?token=secreto")
    with pytest.raises(http.MaterializationError) as caught:
        download(tmp_path)
    assert str(caught.value) == (
        "No se pudo materializar el recurso: revise acceso, tamaño, "
        "tipo de contenido y codificación"
    )
    assert not caplog.text
    assert not sockets


@pytest.mark.parametrize("ip", [PUBLIC, PUBLIC_V6])
def test_public_literal_download(tmp_path, network, ip):
    resolver, sockets, _, _ = network
    resolver.return_value = records(ip)
    host = f"[{ip}]" if ":" in ip else ip
    assert download(tmp_path, f"https://{host}/").read_text() == "hola"
    resolver.assert_called_once_with(ip, 443, type=socket.SOCK_STREAM)
    sockets[0].connect.assert_called_once_with(records(ip)[0][4])


def test_all_connection_failures_close_sockets(tmp_path, network):
    resolver, sockets, replies, _ = network
    resolver.return_value = records(PUBLIC, PUBLIC_V6)
    replies[:] = [OK, OK]
    factory = socket.socket.side_effect

    def fail(*args):
        sock = factory(*args)
        sock.connect.side_effect = OSError("detalle interno")
        return sock

    socket.socket.side_effect = fail
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    resolver.assert_called_once()
    assert len(sockets) == 2
    for sock in sockets:
        sock.close.assert_called_once()


def test_unavailable_address_family_falls_back(network):
    resolver, sockets, _, _ = network
    resolver.return_value = records(PUBLIC_V6, PUBLIC)
    factory = socket.socket.side_effect

    def ipv4_only(family, *args):
        if family == socket.AF_INET6:
            raise OSError("IPv6 no disponible")
        return factory(family, *args)

    socket.socket.side_effect = ipv4_only
    assert http._connect_public(("public.example", 443), 5) is sockets[0]
    sockets[0].connect.assert_called_once_with((PUBLIC, 443))
    resolver.assert_called_once()


def test_tls_verification_failure_remains_fatal(tmp_path, network):
    _, sockets, _, tls = network
    tls.side_effect = ssl.SSLCertVerificationError("certificado inválido")
    with pytest.raises(http.MaterializationError):
        download(tmp_path)
    sockets[0].close.assert_called_once()
    sockets[0].sendall.assert_not_called()
