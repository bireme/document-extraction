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

    NATIVO = "nativo"  # texto embebido, extraíble directo
    ESCANEADO = "escaneado"  # imagen pura, requiere OCR
    MIXTO = "mixto"  # texto parcial


class DocType(str, Enum):
    """Tipo de documento (decide plantilla y estrategia de porción)."""

    ARTICULO = "articulo"  # artículo científico -> plantilla A (IMRAD)
    MANUAL = "manual"  # manual/informe extenso -> plantilla B
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
    # FASE16: detalle opcional por página (fuente nativo/tesseract/vlm,
    # confianza, palabras, chars) para persistir en ocr/<doc_id>.meta.json.
    pages_detail: list[dict] | None = None


@dataclass
class SummarizeRequest:
    """Petición al puerto resumidor: texto + idioma + plantilla objetivo."""

    doc_id: str
    text: str
    lang: str
    template: str


@runtime_checkable
class TextLLM(Protocol):
    """Puerto textual reutilizable; devuelve JSON sin interpretar su contenido."""

    def complete_json(self, prompt: str) -> str: ...


@runtime_checkable
class Summarizer(Protocol):
    """PUERTO del resumidor. Los adaptadores (Ollama, cloud, fake) lo implementan.

    El dominio depende de este Protocol, nunca de una implementación concreta.
    Debe devolver un dict de secciones (nombre_seccion -> contenido).
    """

    def summarize(self, req: SummarizeRequest) -> dict[str, str]: ...


@runtime_checkable
class Transcriber(Protocol):
    """PUERTO de transcripción (Paso 1). Adaptadores: OCR híbrido, pdftotext, fake.

    Convierte un documento (ruta) en texto plano + metadatos. El dominio depende
    de este Protocol, nunca de Tesseract/poppler/VLM directamente.
    """

    def transcribe(self, path: str) -> TranscriptResult: ...


@runtime_checkable
class PageOCR(Protocol):
    """PUERTO de OCR de UNA imagen de pagina (para el fallback VLM).

    Adaptadores: VLM (Ollama vision), fake. El transcriptor hibrido lo usa solo
    cuando Tesseract tiene baja confianza; el hibrido no depende de Ollama.
    """

    def ocr_image(self, image_path: str, lang: str) -> str: ...


@runtime_checkable
class JobStore(Protocol):
    """PUERTO de persistencia de la cola de jobs.

    Guarda/lee el estado de los jobs. Adaptadores: memoria (tests), archivo
    JSON, SQLite. El dominio (queue) depende de este Protocol, no del backend.
    """

    def get(self, key: str) -> dict | None: ...

    def put(self, key: str, value: dict) -> None: ...

    def all(self) -> dict[str, dict]: ...


DOCUMENT_ABSTRACT_VERSION = "2.0"


@dataclass
class DocumentAbstractResult:
    """Resultado exclusivo: resúmenes de origen o un resumen generado."""

    doc_id: str
    idioma_principal: str
    tipo_documento: str
    ai_extracted_abstract: list[Abstract] = field(default_factory=list)
    ai_generated_abstract: str | None = None
    meta: dict = field(default_factory=dict)
    contract_version: str = DOCUMENT_ABSTRACT_VERSION

    def validate(self) -> None:
        if self.contract_version != DOCUMENT_ABSTRACT_VERSION:
            raise ValueError("Versión de contrato desconocida")
        generated = self.ai_generated_abstract
        if generated is not None and not isinstance(generated, str):
            raise ValueError("El resumen generado debe ser texto")
        if bool(self.ai_extracted_abstract) == bool(generated and generated.strip()):
            raise ValueError("Se requiere exclusivamente extracción o generación")
        if not isinstance(self.ai_extracted_abstract, list):
            raise TypeError("Los resúmenes extraídos deben ser una lista")
        for abstract in self.ai_extracted_abstract:
            if not isinstance(abstract, Abstract) or not isinstance(
                abstract.keywords, str
            ):
                raise TypeError("Resumen extraído inválido")
            if not all(
                isinstance(v, str) and v.strip()
                for v in (abstract.lang, abstract.header, abstract.text)
            ):
                raise ValueError("Resumen extraído inválido")

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> DocumentAbstractResult:
        result = cls(
            doc_id=data["doc_id"],
            idioma_principal=data["idioma_principal"],
            tipo_documento=data["tipo_documento"],
            ai_extracted_abstract=[
                Abstract(**a) for a in data["ai_extracted_abstract"]
            ],
            ai_generated_abstract=data["ai_generated_abstract"],
            meta=dict(data.get("meta", {})),
            contract_version=data["contract_version"],
        )
        result.validate()
        return result

    @classmethod
    def from_json(cls, text: str) -> DocumentAbstractResult:
        return cls.from_dict(json.loads(text))


def read_result(data: dict) -> SummaryResult | DocumentAbstractResult:
    """Lee contratos explícitos sin convertir artefactos anteriores."""
    if data.get("contract_version") == DOCUMENT_ABSTRACT_VERSION:
        return DocumentAbstractResult.from_dict(data)
    if data.get("contract_version", CONTRACT_VERSION) == CONTRACT_VERSION:
        if "ai_extracted_abstract" in data or "ai_generated_abstract" in data:
            raise ValueError("Campos incompatibles con el contrato legado")
        return SummaryResult.from_dict(data)
    raise ValueError("Versión de contrato desconocida")


class TextGenerator(Protocol):
    """Puerto de generación textual sin plantillas."""

    def generate_abstract(self, text: str, lang: str) -> str: ...
