"""QA gates: validación automática de un SummaryResult (DOMINIO PURO).

Valida el CONTRATO y la calidad de un resultado, sin modificarlo ni ejecutar
modelos. Gates:
  - schema:    todas las secciones obligatorias de la plantilla, no vacías.
  - refusal:   no hay negativas ni texto dirigido al usuario.
  - lang:      el idioma del resumen coincide con idioma_principal.
  - abstracts: si se detectaron abstracts de origen, están preservados.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .classify import detect_language
from .contract import SummaryResult
from .templates import section_keys

# Frases que delatan refusal o que el modelo se dirige al usuario.
_REFUSAL_MARKERS = [
    "no puedo generar", "no puedo ayudar", "não posso gerar", "não posso",
    "i cannot", "i can't", "as an ai", "i'm sorry", "lo siento, pero",
    "desculpe, mas", "¿cómo puedo ayudar", "como posso ajudar",
    "sua pergunta", "su pregunta", "your question",
]

# Secciones que pueden ir vacías legítimamente (metadatos opcionales).
_OPTIONAL_KEYS = {"autores", "palabras_clave"}


@dataclass
class GateFailure:
    gate: str
    detail: str
    severity: str = "error"


@dataclass
class QAReport:
    doc_id: str
    passed: bool = True
    failures: list[GateFailure] = field(default_factory=list)

    @property
    def is_ok(self) -> bool:
        return not self.failures

    def add(self, gate: str, detail: str, severity: str = "error") -> None:
        self.failures.append(GateFailure(gate, detail, severity))
        self.passed = False

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "passed": self.is_ok,
            "failures": [
                {"gate": f.gate, "detail": f.detail, "severity": f.severity}
                for f in self.failures
            ],
        }


def _gate_schema(res: SummaryResult, rep: QAReport) -> None:
    required = [k for k in section_keys(res.plantilla)
                if k not in _OPTIONAL_KEYS]
    for key in required:
        val = res.secciones.get(key, "").strip()
        if not val:
            rep.add("schema", f"sección obligatoria vacía o ausente: {key}")


def _gate_refusal(res: SummaryResult, rep: QAReport) -> None:
    blob = "\n".join(res.secciones.values()).lower()
    for marker in _REFUSAL_MARKERS:
        if marker in blob:
            rep.add("refusal", f"marca de refusal/dirigido al usuario: '{marker}'")
            return


def _gate_language(res: SummaryResult, rep: QAReport) -> None:
    blob = " ".join(res.secciones.values())
    if len(blob.split()) < 8:
        return  # texto insuficiente para juzgar idioma
    detected = detect_language(blob)
    if detected != "unknown" and detected != res.idioma_principal:
        rep.add("lang",
                f"idioma del resumen '{detected}' != principal "
                f"'{res.idioma_principal}'", severity="warning")


def _gate_abstracts(res: SummaryResult, rep: QAReport) -> None:
    declared = set(res.idiomas_resumo_origem)
    present = {a.lang for a in res.abstracts_origem}
    if declared and declared != present:
        rep.add("abstracts",
                f"abstracts declarados {sorted(declared)} != "
                f"preservados {sorted(present)}")


def check_result(res: SummaryResult) -> QAReport:
    """Aplica todos los gates y devuelve el reporte agregado."""
    rep = QAReport(doc_id=res.doc_id)
    _gate_schema(res, rep)
    _gate_refusal(res, rep)
    _gate_language(res, rep)
    _gate_abstracts(res, rep)
    return rep
