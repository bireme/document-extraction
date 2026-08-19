"""Contrato de datos del dominio (frontera estable).

Define los tipos que cruzan la frontera del motor y el PUERTO del resumidor.
Este módulo es DOMINIO PURO: no importa adaptadores (Ollama, Tesseract, HTTP),
no ejecuta modelos ni procesos externos. Solo estructuras y contratos.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

CONTRACT_VERSION = "1.0"


class SourceKind(str, Enum):
    """Origen del texto del PDF."""

    NATIVO = "nativo"        # texto embebido, extraíble directo
    ESCANEADO = "escaneado"  # imagen pura, requiere OCR
    MIXTO = "mixto"          # texto parcial


class DocType(str, Enum):
    """Tipo de documento (decide plantilla y estrategia de porción)."""

    ARTICULO = "articulo"        # artículo científico -> plantilla A (IMRAD)
    MANUAL = "manual"            # manual/informe extenso -> plantilla B
    DIVULGACION = "divulgacion"  # folleto/cartaz/edital -> plantilla C


# Mapa tipo -> plantilla (letra usada en el informe §3.1).
TEMPLATE_BY_TYPE: dict[DocType, str] = {
    DocType.ARTICULO: "A",
    DocType.MANUAL: "B",
    DocType.DIVULGACION: "C",
}


@dataclass
class Abstract:
    """Un resumen de origen preservado verbatim (no traducir ni fusionar)."""

    lang: str
    header: str
    text: str
    keywords: str = ""


@dataclass
class SummaryResult:
    """Resultado del motor para un documento. Frontera estable (serializa a JSON).

    Campos obligatorios del contrato: doc_id, idioma_principal,
    idiomas_resumo_origem, tipo_documento, plantilla, secciones,
    abstracts_origem, meta.
    """

    doc_id: str
    idioma_principal: str
    tipo_documento: str
    plantilla: str
    secciones: dict[str, str] = field(default_factory=dict)
    idiomas_resumo_origem: list[str] = field(default_factory=list)
    abstracts_origem: list[Abstract] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    contract_version: str = CONTRACT_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> SummaryResult:
        abstracts = [Abstract(**a) for a in d.get("abstracts_origem", [])]
        return cls(
            doc_id=d["doc_id"],
            idioma_principal=d["idioma_principal"],
            tipo_documento=d["tipo_documento"],
            plantilla=d["plantilla"],
            secciones=dict(d.get("secciones", {})),
            idiomas_resumo_origem=list(d.get("idiomas_resumo_origem", [])),
            abstracts_origem=abstracts,
            meta=dict(d.get("meta", {})),
            contract_version=d.get("contract_version", CONTRACT_VERSION),
        )

    @classmethod
    def from_json(cls, s: str) -> SummaryResult:
        return cls.from_dict(json.loads(s))


@dataclass
class TranscriptResult:
    """Salida del puerto de transcripción (Paso 1): texto + metadatos."""

    text: str
    pages: int
    source_kind: SourceKind


@dataclass
class SummarizeRequest:
    """Petición al puerto resumidor: texto + idioma + plantilla objetivo."""

    doc_id: str
    text: str
    lang: str
    template: str


@runtime_checkable
class Summarizer(Protocol):
    """PUERTO del resumidor. Los adaptadores (Ollama, cloud, fake) lo implementan.

    El dominio depende de este Protocol, nunca de una implementación concreta.
    Debe devolver un dict de secciones (nombre_seccion -> contenido).
    """

    def summarize(self, req: SummarizeRequest) -> dict[str, str]:
        ...


@runtime_checkable
class Transcriber(Protocol):
    """PUERTO de transcripción (Paso 1). Adaptadores: OCR híbrido, pdftotext, fake.

    Convierte un documento (ruta) en texto plano + metadatos. El dominio depende
    de este Protocol, nunca de Tesseract/poppler/VLM directamente.
    """

    def transcribe(self, path: str) -> TranscriptResult:
        ...
