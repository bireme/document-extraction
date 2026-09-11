"""Materialización HTTP por streaming, con validación y errores sin secretos."""

from __future__ import annotations

import codecs
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

from ..external import ExternalInput


class MaterializationError(ValueError):
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
        _validate_url(req.full_url)
        return self.do_open(partial(_public_connection, HTTPConnection), req)


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, req):
        _validate_url(req.full_url)
        return self.do_open(partial(_public_connection, HTTPSConnection), req)


def _validate_url(value: str) -> None:
    url = urlsplit(value)
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
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_http(url: str, *, timeout: float):
    return build_opener(
        ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler(), _HTTPRedirect()
    ).open(url, timeout=timeout)


class HTTPMaterializer:
    """Acepta PDF y texto Unicode; normaliza el texto validado a UTF-8.

    Sin charset explícito se exige UTF-8 estricto. El límite de tamaño se
    aplica también cuando el servidor no proporciona Content-Length.
    Un opener inyectado es transporte de confianza y debe imponer su propia SSRF.
    """

    def __init__(
        self, *, timeout: float = 30, max_bytes: int = 100_000_000, opener=_open_http
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0 or max_bytes <= 0:
            raise ValueError("Timeout y límite de descarga deben ser positivos")
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.opener = opener

    def materialize(self, entry: ExternalInput, destination: Path) -> None:
        created = False
        try:
            _validate_url(entry.url)
            if entry.input_type not in {"pdf", "text"}:
                raise ValueError("Tipo de entrada no admitido")
            with self.opener(entry.url, timeout=self.timeout) as response:
                if not 200 <= response.status < 300:
                    raise ValueError("Estado HTTP no satisfactorio")
                content_type = response.headers.get_content_type()
                allowed = (
                    {"application/pdf", "application/octet-stream"}
                    if entry.input_type == "pdf"
                    else {"text/plain", "text/markdown", "application/octet-stream"}
                )
                if response.headers.get("Content-Type") and content_type not in allowed:
                    raise ValueError("Content-Type incompatible")
                decoder = None
                if entry.input_type == "text":
                    charset = response.headers.get_content_charset() or "utf-8-sig"
                    encoding = codecs.lookup(charset).name
                    if encoding not in {
                        "utf-8",
                        "utf-8-sig",
                        "utf-16",
                        "utf-16-le",
                        "utf-16-be",
                    }:
                        raise ValueError("Codificación de texto no admitida")
                    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
                count = 0
                prefix = b""
                tail = b""
                has_text = False
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
                        if decoder is None:
                            output.write(chunk)
                        else:
                            text = decoder.decode(chunk)
                            self._validate_text(text)
                            has_text = has_text or bool(text.strip())
                            output.write(text.encode("utf-8"))
                    if decoder is not None:
                        text = decoder.decode(b"", final=True)
                        self._validate_text(text)
                        has_text = has_text or bool(text.strip())
                        output.write(text.encode("utf-8"))
                if not count:
                    raise ValueError("Respuesta vacía")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != count:
                    raise ValueError("Respuesta incompleta")
                if entry.input_type == "pdf":
                    if not re.match(rb"%PDF-\d\.\d", prefix) or b"%%EOF" not in tail:
                        raise ValueError("Contenido PDF inválido")
                elif not has_text or prefix.startswith(b"%PDF-"):
                    raise ValueError("Contenido de texto inválido")
        except Exception:  # noqa: BLE001 — sanitizar errores de proveedores
            if created:
                destination.unlink(missing_ok=True)
            # Las excepciones HTTP pueden contener la URL y credenciales.
            raise MaterializationError(
                "No se pudo materializar el recurso: revise acceso, tamaño, "
                "tipo de contenido y codificación"
            ) from None

    @staticmethod
    def _validate_text(text: str) -> None:
        if any(ord(char) < 32 and char not in "\n\r\t\f" for char in text):
            raise ValueError("El recurso contiene controles binarios")
