"""Materialización HTTP por streaming, con validación y errores sin secretos."""

from __future__ import annotations

import ipaddress
import math
import re
import socket
from functools import partial
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    build_opener,
)


class DownloadError(ValueError):
    """Recurso inaccesible, vacío o incompatible con el tipo declarado."""


class _PublicDestinations:
    """Política del transporte; una futura allowlist debe ser explícita."""

    @staticmethod
    def validate_ip(address):
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
        ):
            raise ValueError("Destino HTTP no permitido")
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            _PublicDestinations.validate_ip(address.ipv4_mapped)

    @classmethod
    def validate_host(cls, host):
        name = host.lower().rstrip(".")
        if (
            not name
            or "%" in name
            or name
            in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
            or name.endswith((".localhost", ".local", ".localdomain"))
        ):
            raise ValueError("Destino HTTP no permitido")
        try:
            address = ipaddress.ip_address(name)
        except ValueError:
            return  # Los nombres, incluidas notaciones IP alternativas, pasan por DNS.
        cls.validate_ip(address)


def _connect_public(address, timeout, source_address=None):
    """Valida todo el resultado DNS antes de crear sockets; nunca vuelve a resolver."""
    host, port = address
    _PublicDestinations.validate_host(host)
    candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not candidates:
        raise ValueError("Destino HTTP no permitido")
    validated = []
    for family, socktype, proto, _, sockaddr in candidates:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            raise ValueError("Destino HTTP no permitido")
        ip = ipaddress.ip_address(sockaddr[0])
        _PublicDestinations.validate_ip(ip)
        # Direcciones numéricas canónicas: socket.connect no necesita resolver DNS.
        validated.append((family, socktype, proto, (str(ip), *sockaddr[1:])))
    for family, socktype, proto, sockaddr in validated:
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError:
            if sock is not None:
                sock.close()
    raise OSError("No se pudo conectar al destino HTTP")


def _public_connection(connection_type, *args, **kwargs):
    connection = connection_type(*args, **kwargs)
    # Hook privado de http.client: conserva connect() y todo el TLS estándar,
    # incluido SNI y la comprobación del certificado con el hostname original.
    connection._create_connection = _connect_public
    return connection


class _PublicHTTPHandler(HTTPHandler):
    def http_open(self, req):
        validate_pdf_url(req.full_url)
        return self.do_open(partial(_public_connection, HTTPConnection), req)


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        validate_pdf_url(req.full_url)
        return self.do_open(partial(_public_connection, HTTPSConnection), req)


def validate_pdf_url(value: str) -> None:
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise ValueError("URL HTTP inválida")
    url = urlsplit(value)
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("Puerto HTTP inválido")
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
    ):
        raise ValueError("URL HTTP inválida")
    _PublicDestinations.validate_host(url.hostname)


class _HTTPRedirect(HTTPRedirectHandler):
    """Aplica las mismas restricciones a cada destino de redirección."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_pdf_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_http(url: str, *, timeout: float):
    return build_opener(
        ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler(), _HTTPRedirect()
    ).open(url, timeout=timeout)


class PDFDownloader:
    """Descarga únicamente PDF con límites y transporte público validado.

    El timeout se aplica a las operaciones del socket. Un opener inyectado
    es transporte de confianza y debe imponer su propia protección SSRF.
    """

    def __init__(
        self, *, timeout: float = 30, max_bytes: int = 100_000_000, opener=_open_http
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0 or max_bytes <= 0:
            raise ValueError("Timeout y límite de descarga deben ser positivos")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = opener

    def download(self, url: str, destination: Path) -> None:
        """Valida el contenido y elimina cualquier descarga parcial propia."""
        created = False
        try:
            validate_pdf_url(url)
            with self.opener(url, timeout=self.timeout) as response:
                if response.status != 200:
                    raise ValueError("Estado HTTP no satisfactorio")
                content_type = response.headers.get_content_type()
                if response.headers.get("Content-Type") and content_type not in {
                    "application/pdf",
                    "application/octet-stream",
                }:
                    raise ValueError("Content-Type incompatible")
                length = response.headers.get("Content-Length")
                if length is not None and not 0 < int(length) <= self.max_bytes:
                    raise ValueError("Tamaño HTTP inválido")
                count = 0
                prefix = b""
                tail = b""
                with destination.open("xb") as output:
                    created = True
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > self.max_bytes:
                            raise ValueError("Recurso demasiado grande")
                        prefix = (prefix + chunk)[:1024]
                        tail = (tail + chunk)[-2048:]
                        output.write(chunk)
                if not count:
                    raise ValueError("Respuesta vacía")
                if length is not None and int(length) != count:
                    raise ValueError("Respuesta incompleta")
                if not re.match(rb"%PDF-\d\.\d", prefix) or b"%%EOF" not in tail:
                    raise ValueError("Contenido PDF inválido")
        except Exception:  # noqa: BLE001 — sanitizar errores del transporte
            if created:
                try:
                    destination.unlink(missing_ok=True)
                except OSError:
                    pass  # El dueño del workspace vuelve a intentar el cleanup.
            # Las excepciones del transporte pueden contener credenciales o tokens.
            raise DownloadError(
                "No se pudo descargar el PDF: revise acceso, tamaño y contenido"
            ) from None
