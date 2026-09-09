"""Pruebas offline de revisión, transporte y composición de la CLI."""

import json
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest

from pdfsum.abstract_refine import refine_abstracts
from pdfsum.abstracts import extract_abstracts
from pdfsum.adapters.abstract_batch import extract_abstracts_from_pdfs
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.summarizer_factory import build_summarizer
from pdfsum.cli import main
from pdfsum.contract import Abstract, SummarizeRequest, TextLLM
from pdfsum.workspace import Workspace

BODY = "Este estudio describe los resultados de una intervención comunitaria."
SOURCE = "RESUMEN\n" + BODY + "\nPalabras clave: salud; comunidad."


def respuesta(abstracts):
    return json.dumps({"abstracts": [asdict(a) for a in abstracts]})


@pytest.mark.parametrize(
    "context,candidates,expected",
    [
        (SOURCE, extract_abstracts(SOURCE), extract_abstracts(SOURCE)),
        (
            SOURCE,
            [Abstract("es", "RESUMEN", "Este estudio")],
            [Abstract("es", "RESUMEN", BODY, "salud; comunidad.")],
        ),
        (
            SOURCE + "\nINTRODUCCIÓN\nTexto posterior.",
            [Abstract("es", "RESUMEN", BODY + " Texto posterior.")],
            [Abstract("es", "RESUMEN", BODY)],
        ),
        (
            SOURCE,
            [Abstract("es", "RESUMEN", BODY + " Palabras clave: salud;")],
            [Abstract("es", "RESUMEN", BODY, "salud; comunidad.")],
        ),
        (
            "RESUMO\nA forma- tação foi corrigida no documento original.",
            [],
            [
                Abstract(
                    "pt", "RESUMO", "A formatação foi corrigida no documento original."
                )
            ],
        ),
        (
            "RESUMO\nEste estudo teve como objetivo investigar a saúde coletiva.",
            [],
            [
                Abstract(
                    "pt",
                    "RESUMO",
                    "Este estudo teve como objetivo investigar a saúde coletiva.",
                )
            ],
        ),
        ("INTRODUCCIÓN\n" + BODY, [], []),
        (
            "RESUMO\nTexto em português.\nABSTRACT\nEnglish text.\nRESUMEN\nTexto español.",
            [],
            [
                Abstract("pt", "RESUMO", "Texto em português."),
                Abstract("en", "ABSTRACT", "English text."),
                Abstract("es", "RESUMEN", "Texto español."),
            ],
        ),
    ],
)
def test_revision(context, candidates, expected):
    llm = FakeSummarizer(respuesta(expected))
    assert refine_abstracts(context, candidates, llm) == expected


def test_recupera_resumen_mayor_del_limite_determinista():
    body = "La intervención produjo resultados observables en la comunidad. " * 50
    context = "RESUMEN\n" + body
    candidates = extract_abstracts(context)
    assert len(candidates[0].text) <= 2500
    expected = [Abstract("es", "RESUMEN", body.strip())]
    assert (
        refine_abstracts(context, candidates, FakeSummarizer(respuesta(expected)))
        == expected
    )


@pytest.mark.parametrize("limit", [20_000, 500])
def test_contexto_y_candidatos_no_filtran_el_resto(limit):
    context = SOURCE + " " * limit + "RESUMEN\nSECRETO FUERA DEL CONTEXTO"
    candidates = extract_abstracts(SOURCE)
    candidates[0].keywords = "SECRETO FUERA DEL CONTEXTO"
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = '{"abstracts": []}'
    assert refine_abstracts(context, candidates, llm, limit) == []
    prompt = llm.complete_json.call_args.args[0]
    data = json.loads(prompt.split("\n")[-1])
    assert data["transcription"] == context[:limit]
    assert "SECRETO" not in prompt


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "no es JSON",
        "```json\n{}\n```",
        "{}",
        "[]",
        '{"abstracts": null}',
        '{"abstracts": [null]}',
        '{"abstracts": [{"text": 3}]}',
        respuesta([Abstract("es", "RESUMEN", "")]),
        respuesta([Abstract("es", "RESUMEN", "La vacuna curó a todos los pacientes.")]),
        respuesta([Abstract("es", "RESUMEN", BODY, 123)]),
        respuesta([Abstract("en", "RESUMEN", BODY)]),
        respuesta([Abstract("es", "RESUMEN", BODY * 2000)]),
        TimeoutError("sin conexión"),
    ],
)
def test_fallback_y_continuidad_del_lote(tmp_path, caplog, raw):
    ws = Workspace(str(tmp_path / "salida"))
    inputs = tmp_path / "entrada"
    inputs.mkdir()
    for name in ("a", "b"):
        (inputs / f"{name}.pdf").touch()
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [raw, respuesta(extract_abstracts(SOURCE))]
    report = extract_abstracts_from_pdfs(str(inputs), ws, FakeTranscriber(SOURCE), llm)
    assert report["total"] == report["found"] == 2
    assert report["documents"][0]["abstracts"] == [
        asdict(a) for a in extract_abstracts(SOURCE)
    ]
    assert "abstract_refine_fallback" in [
        getattr(r, "event", "") for r in caplog.records
    ]
    assert ws.abstract_path("b").exists()


def test_fake_conserva_candidatos_sin_red():
    candidates = extract_abstracts(SOURCE)
    assert refine_abstracts(SOURCE, candidates, FakeSummarizer()) == candidates


def test_preserva_keywords_detectadas_si_el_llm_las_omite():
    candidates = extract_abstracts(SOURCE)
    llm = FakeSummarizer(respuesta([Abstract("es", "RESUMEN", BODY)]))
    assert refine_abstracts(SOURCE, candidates, llm) == candidates


def test_json_vacio_valido_elimina_falso_positivo():
    assert (
        refine_abstracts(
            "INTRODUCCIÓN\n" + BODY,
            [Abstract("es", "RESUMEN", BODY)],
            FakeSummarizer('{"abstracts": []}'),
        )
        == []
    )


def test_cache_y_configuracion_de_contexto(tmp_path):
    ws = Workspace(str(tmp_path / "salida"))
    ws.ocr_dir.mkdir(parents=True)
    ws.ocr_path("a").write_text(SOURCE + " RESTO EXCLUIDO", encoding="utf-8")
    (tmp_path / "a.pdf").touch()
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = '{"abstracts": []}'
    transcriber = Mock()
    with (
        patch(
            "pdfsum.config.load_config",
            return_value={"abstract_refine_context_chars": len(SOURCE)},
        ),
        patch("pdfsum.cli._build_summarizer", return_value=llm),
        patch("pdfsum.cli._build_transcriber", return_value=transcriber),
    ):
        assert (
            main(
                [
                    "extract-abstracts",
                    "--in",
                    str(tmp_path),
                    "--workspace",
                    str(ws.root),
                    "--dry-run",
                ]
            )
            == 0
        )
    transcriber.transcribe.assert_not_called()
    assert "RESTO EXCLUIDO" not in llm.complete_json.call_args.args[0]


def test_preflight_fallido_no_procesa_documentos(tmp_path):
    with (
        patch("pdfsum.cli._preflight_resumen", return_value=2),
        patch("pdfsum.cli._build_summarizer") as build,
    ):
        assert (
            main(
                [
                    "extract-abstracts",
                    "--in",
                    str(tmp_path),
                    "--workspace",
                    str(tmp_path / "salida"),
                ]
            )
            == 2
        )
    build.assert_not_called()


class Response:
    """Respuesta HTTP simulada."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.body).encode()


@pytest.mark.parametrize("backend", ["ollama", "openai", "openrouter", "anthropic"])
def test_misma_instancia_modelo_y_transporte(backend, monkeypatch):
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "prueba")
    outputs = iter([respuesta(extract_abstracts(SOURCE)), "## Título\nResultado"])
    calls = []

    def urlopen(req, timeout):
        calls.append((req.full_url, json.loads(req.data)))
        text = next(outputs)
        return Response(
            {
                "response": text,
                "choices": [{"message": {"content": text}}],
                "content": [{"type": "text", "text": text}],
            }
        )

    llm = build_summarizer(backend, "modelo-elegido")
    assert isinstance(llm, TextLLM)
    with patch("urllib.request.urlopen", side_effect=urlopen):
        assert refine_abstracts(SOURCE, extract_abstracts(SOURCE), llm)
        assert (
            llm.summarize(SummarizeRequest("doc", SOURCE, "es", "C"))["titulo"]
            == "Resultado"
        )
    assert all(body["model"] == "modelo-elegido" for _, body in calls)
    assert calls[0][0] == calls[1][0]
    body = calls[0][1]
    if backend == "ollama":
        assert body["format"] == "json"
        assert body["options"]["temperature"] == 0
    else:
        assert body["temperature"] == 0
        if backend != "anthropic":
            assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("backend", [None, "openai", "openrouter", "anthropic"])
def test_cli_resuelve_una_vez_y_reutiliza_cliente(tmp_path, monkeypatch, backend):
    monkeypatch.delenv("PDFSUM_SUMMARIZER_BACKEND", raising=False)
    for name in ("a", "b"):
        (tmp_path / f"{name}.pdf").touch()
    llm = FakeSummarizer()
    args = [
        "extract-abstracts",
        "--in",
        str(tmp_path),
        "--workspace",
        str(tmp_path / "salida"),
        "--model",
        "modelo-elegido",
    ]
    if backend:
        args += ["--backend", backend]
    with (
        patch("pdfsum.config.load_config", return_value={}),
        patch("pdfsum.cli._preflight_resumen", return_value=None) as preflight,
        patch("pdfsum.cli._build_transcriber", return_value=FakeTranscriber(SOURCE)),
        patch("pdfsum.cli._build_summarizer", return_value=llm) as build,
        patch.object(llm, "complete_json", wraps=llm.complete_json) as complete,
    ):
        assert main(args) == 0
    build.assert_called_once_with(False, backend or "ollama", "modelo-elegido")
    preflight.assert_called_once_with("modelo-elegido", backend or "ollama")
    assert complete.call_count == 2


@pytest.mark.parametrize("flag", ["--fake", "--dry-run"])
def test_cli_modos_offline(tmp_path, flag):
    (tmp_path / "a.pdf").touch()
    with (
        patch("pdfsum.cli._preflight_resumen") as preflight,
        patch("pdfsum.cli._build_transcriber", return_value=FakeTranscriber(SOURCE)),
        patch("urllib.request.urlopen", side_effect=AssertionError("Red prohibida")),
    ):
        assert (
            main(
                [
                    "extract-abstracts",
                    "--in",
                    str(tmp_path),
                    "--workspace",
                    str(tmp_path / "salida"),
                    flag,
                ]
            )
            == 0
        )
    preflight.assert_not_called()
