"""Contrato textual, prioridad de extracción y generación jerárquica."""

import json
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest

from pdfsum.abstract_extraction import extract_refined_abstracts
from pdfsum.abstract_generation import (
    document_abstract_result,
    generate_document_abstract,
)
from pdfsum.adapters.batch_runner import run_batch
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.adapters.summarizer_factory import (
    LazyGenerator,
    build_reviewer,
    resolve_task_backend,
    resolve_task_model,
)
from pdfsum.cli import build_parser, main
from pdfsum.contract import (
    Abstract,
    DocumentAbstractResult,
    SummaryResult,
    TextGenerator,
    TextLLM,
    read_result,
)
from pdfsum.export import to_lilacs
from pdfsum.qa import check_result
from pdfsum.workspace import Workspace

BODY = "Este estudio describe los resultados de una intervención comunitaria y evalúa sus beneficios para la salud pública."
SOURCE = "RESUMEN\n" + BODY


@pytest.mark.parametrize("count", [1, 2, 3])
def test_extraidos_sin_generacion(count):
    abstracts = [Abstract("es", "RESUMEN", BODY + str(i)) for i in range(count)]
    generator = Mock(spec=TextGenerator)
    result = document_abstract_result("doc", SOURCE, generator, abstracts)
    assert result.ai_extracted_abstract == abstracts
    assert result.ai_generated_abstract is None
    generator.generate_abstract.assert_not_called()
    assert check_result(result).is_ok
    assert result.meta["abstract_source"] == "extracted"


def test_sin_abstract_genera_un_texto():
    generator = Mock(spec=TextGenerator)
    generator.generate_abstract.return_value = BODY
    result = document_abstract_result(
        "doc", "Contenido sin encabezados.", generator, []
    )
    generator.generate_abstract.assert_called_once()
    assert result.ai_extracted_abstract == []
    assert result.ai_generated_abstract == BODY
    assert "secciones" not in result.to_dict()
    assert "plantilla" not in result.to_dict()


@pytest.mark.parametrize("prefix", ["Contenido previo. " * 80 + "\n", "X" * 460 + "\n"])
def test_revision_fuera_de_ventana_y_en_el_limite(prefix):
    reviewer = FakeSummarizer()
    with patch.object(reviewer, "complete_json", wraps=reviewer.complete_json) as calls:
        result = extract_refined_abstracts(prefix + SOURCE, reviewer, 500)
    assert [a.text for a in result.abstracts] == [BODY]
    assert calls.call_count >= 2
    prompts = [json.loads(c.args[0].splitlines()[-1]) for c in calls.call_args_list]
    assert any(BODY in p["transcription"] for p in prompts)
    assert all(len(p["transcription"]) <= 500 for p in prompts)


def test_fallo_revision_preserva_fallback_y_evitar_generacion(tmp_path):
    (tmp_path / "doc.pdf").touch()
    reviewer = Mock(spec=TextLLM)
    reviewer.complete_json.side_effect = TimeoutError("Revisión demorada")
    generator = Mock(spec=TextGenerator)
    ws = Workspace(tmp_path / "salida")
    report = run_batch_pdfs(
        str(tmp_path), ws, FakeTranscriber(SOURCE), generator, abstract_llm=reviewer
    )
    generator.generate_abstract.assert_not_called()
    result = read_result(json.loads(ws.summary_path("doc").read_text()))
    assert result.ai_extracted_abstract[0].text == BODY
    assert report["metrics"]["generacion_evitada"] == 1
    assert report["metrics"]["abstracts_extraidos"] == 1
    assert report["metrics"]["abstracts_generados"] == 0
    assert result.meta["abstract_extraction"]["fallback"]


def test_preflight_lazy_aisla_fallo_y_reutiliza_ocr(tmp_path):
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    (entrada / "doc.pdf").write_bytes(b"%PDF-1.4")
    ws = Workspace(tmp_path / "salida")
    transcriber = FakeTranscriber(SOURCE)
    with patch(
        "pdfsum.adapters.doctor.summarization_ready",
        return_value=(False, "No disponible"),
    ) as ready:
        generator = LazyGenerator("ollama", "ausente")
        report = run_batch_pdfs(str(entrada), ws, transcriber, generator)
        assert report["progress"]["completed"] == 1
        ready.assert_not_called()
        with patch.object(
            transcriber, "transcribe", side_effect=AssertionError("OCR repetido")
        ):
            run_batch_pdfs(str(entrada), ws, transcriber, generator)
        ready.assert_not_called()
        (entrada / "otro.pdf").write_bytes(b"%PDF-1.4 otro")
        report = run_batch_pdfs(
            str(entrada), ws, FakeTranscriber("Contenido sin resumen."), generator
        )
        assert report["progress"]["completed"] == 1
        assert report["progress"]["failed"] == 1
        assert not ws.summary_path("otro").exists()
        ready.assert_called_once_with("ausente", backend="ollama")


def test_revisor_ausente_activa_fallback():
    with patch(
        "pdfsum.adapters.doctor.summarization_ready",
        return_value=(False, "Revisor ausente"),
    ):
        reviewer = build_reviewer("ollama", "ausente")
    result = extract_refined_abstracts(SOURCE, reviewer)
    assert result.abstracts[0].text == BODY
    assert result.diagnostics()["fallback"]


def test_summarize_no_extrae_ni_parsea_secciones(tmp_path, capsys):
    source = tmp_path / "doc.txt"
    source.write_text(SOURCE)
    with (
        patch(
            "pdfsum.abstract_extraction.extract_refined_abstracts",
            side_effect=AssertionError("Extracción prohibida"),
        ),
        patch(
            "pdfsum.abstracts.extract_abstracts",
            side_effect=AssertionError("Extracción prohibida"),
        ),
        patch(
            "pdfsum.adapters.llm_prompt.parse_sections",
            side_effect=AssertionError("Secciones prohibidas"),
        ),
        patch(
            "pdfsum.adapters.summarizer_factory.build_reviewer",
            side_effect=AssertionError("Revisión prohibida"),
        ),
    ):
        assert main(["summarize", "--text", str(source), "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ai_generated_abstract"]
    assert result["ai_extracted_abstract"] == []


@pytest.mark.parametrize("adapter", ["ollama", "cloud", "anthropic"])
def test_adapters_generan_texto_directo(adapter):
    from pdfsum.adapters.anthropic_summarizer import AnthropicSummarizer
    from pdfsum.adapters.cloud_summarizer import CloudSummarizer
    from pdfsum.adapters.ollama_summarizer import OllamaSummarizer

    cls = {
        "ollama": OllamaSummarizer,
        "cloud": CloudSummarizer,
        "anthropic": AnthropicSummarizer,
    }[adapter]
    llm = cls()
    with patch.object(llm, "_call", return_value=BODY) as call:
        assert llm.generate_abstract(SOURCE, "es") == BODY
    prompt = call.call_args.args[0]
    assert "solamente el texto" in prompt
    assert SOURCE in prompt
    assert "##" not in prompt
    assert call.call_args.kwargs == {}


def test_modelos_defaults_y_precedencia(monkeypatch):
    monkeypatch.delenv("PDFSUM_ABSTRACT_MODEL", raising=False)
    monkeypatch.delenv("PDFSUM_SUMMARY_MODEL", raising=False)
    with patch("pdfsum.config.load_config", return_value={}):
        assert resolve_task_model("ollama", "abstract") == "qwen2.5:7b"
        assert resolve_task_model("ollama", "summary") == "qwen3:8b"
        assert resolve_task_model("anthropic", "summary") == "claude-haiku-4-5"
        assert resolve_task_model("ollama", "summary", "llama-local") == "llama-local"
    with patch(
        "pdfsum.config.load_config",
        return_value={"abstract_model": "revisor", "summary_model": "generador"},
    ):
        assert resolve_task_model("ollama", "abstract") == "revisor"
        assert resolve_task_model("ollama", "summary") == "generador"
        monkeypatch.setenv("PDFSUM_SUMMARY_MODEL", "entorno")
        assert resolve_task_model("ollama", "summary") == "entorno"
        assert resolve_task_model("ollama", "summary", "cli") == "cli"
        assert resolve_task_model("ollama", "abstract") == "revisor"


def test_modelo_generico_no_se_propaga(caplog):
    with (
        patch.dict("os.environ", {}, clear=True),
        patch(
            "pdfsum.config.load_config",
            return_value={"model": "viejo", "cloud_model": "viejo-cloud"},
        ),
    ):
        assert resolve_task_model("ollama", "abstract") == "qwen2.5:7b"
        assert resolve_task_model("ollama", "summary") == "qwen3:8b"
    assert "flujo legado" in caplog.text


def test_backends_independientes(monkeypatch):
    monkeypatch.delenv("PDFSUM_SUMMARIZER_BACKEND", raising=False)
    with patch(
        "pdfsum.config.load_config",
        return_value={"abstract_backend": "ollama", "summary_backend": "anthropic"},
    ):
        assert resolve_task_backend("abstract") == "ollama"
        assert resolve_task_backend("summary") == "anthropic"
        monkeypatch.setenv("PDFSUM_SUMMARY_BACKEND", "openrouter")
        assert resolve_task_backend("summary") == "openrouter"
        assert resolve_task_backend("summary", "openai") == "openai"
        assert resolve_task_backend("summary", shared="ollama") == "ollama"


class RecordingGenerator:
    def __init__(self):
        self.inputs = []

    def generate_abstract(self, text, lang):
        self.inputs.append(text)
        return "Síntesis breve del contenido recibido."


def test_hierarquia_cubre_prefacio_encabezados_y_final():
    text = "PREFACIO IMPORTANTE\n" + "Antecedentes. " * 30
    text += "\nCapítulo\n1\nPRIMER TEMA\n" + "Contenido primero. " * 50
    text += (
        "\nCapítulo\n2\nSEGUNDO TEMA\n"
        + "Contenido segundo. " * 50
        + "CIERRE IMPORTANTE"
    )
    generator = RecordingGenerator()
    result = generate_document_abstract("doc", text, generator, max_chars=200)
    assert result.meta["excerpt_strategy"] == "hierarchical"
    assert result.meta["excerpt_chars"] == len(text)
    assert not result.meta["excerpt_truncated"]
    assert all(len(t) <= 200 for t in generator.inputs)
    # Las llamadas de primera pasada conservan todos los caracteres no blancos.
    original_parts = [t for t in generator.inputs if "Síntesis breve" not in t]
    assert "".join("".join(original_parts).split()) == "".join(text.split())
    assert result.meta["input_calls"] == len(generator.inputs)
    assert result.meta["input_calls"] > len(original_parts)
    assert isinstance(result.ai_generated_abstract, str)


def test_reduccion_multinivel_sin_recorte():
    generator = RecordingGenerator()
    text = "Documento largo sin capítulos. " * 300
    result = generate_document_abstract("doc", text, generator, max_chars=120)
    assert result.meta["excerpt_strategy"] == "blocks"
    assert all(len(t) <= 120 for t in generator.inputs)
    assert sum("Síntesis breve" in t for t in generator.inputs) > 2
    assert result.meta["input_calls"] == len(generator.inputs)
    assert result.ai_generated_abstract


@pytest.mark.parametrize("detected,expected", [("unknown", "pt"), ("es", "es")])
def test_idioma_principal_coincide_en_ambos_caminos(detected, expected):
    generator = Mock(spec=TextGenerator)
    generator.generate_abstract.return_value = BODY
    with patch("pdfsum.abstract_generation.detect_language", return_value=detected):
        extracted = document_abstract_result(
            "doc", SOURCE, generator, [Abstract("es", "RESUMEN", BODY)]
        )
        generator.generate_abstract.assert_not_called()
        generated = document_abstract_result("doc", SOURCE, generator, [])
    assert extracted.idioma_principal == generated.idioma_principal == expected
    generator.generate_abstract.assert_called_once_with(SOURCE, expected)
    assert generated.meta["input_calls"] == 1


def test_reduccion_que_no_comprime_falla():
    generator = Mock(spec=TextGenerator)
    generator.generate_abstract.side_effect = lambda text, lang: text
    with pytest.raises(ValueError, match="no comprime"):
        generate_document_abstract(
            "doc", "Texto largo. " * 100, generator, max_chars=100
        )


@pytest.mark.parametrize("value", [None, "", "   ", {}, '{"resumen":"texto"}'])
def test_generacion_invalida_no_es_exito(value):
    generator = Mock(spec=TextGenerator)
    generator.generate_abstract.return_value = value
    with pytest.raises(ValueError):
        generate_document_abstract("doc", "Contenido.", generator)


@pytest.mark.parametrize(
    "abstracts,generated",
    [
        ([], None),
        ([], ""),
        ([Abstract("es", "RESUMEN", BODY)], BODY),
        ([Abstract("es", "", BODY)], None),
    ],
)
def test_qa_rechaza_contratos_inconsistentes(abstracts, generated):
    result = DocumentAbstractResult("doc", "es", "articulo", abstracts, generated)
    assert not check_result(result).is_ok
    with pytest.raises(ValueError):
        result.to_json()


def test_serializacion_y_export_de_ambos_contratos():
    legacy = SummaryResult("viejo", "es", "articulo", "A", {"objetivo": BODY})
    new = DocumentAbstractResult(
        "nuevo", "es", "articulo", [Abstract("es", "RESUMEN", BODY)]
    )
    for original in (legacy, new):
        assert type(read_result(json.loads(original.to_json()))) is type(original)
        assert (
            read_result(json.loads(original.to_json())).to_dict() == original.to_dict()
        )
        assert (
            to_lilacs(original)["origen"]["contract_version"]
            == original.contract_version
        )
    assert to_lilacs(new)["lilacs"]["ai_extracted_abstract"] == [
        asdict(new.ai_extracted_abstract[0])
    ]
    assert "secciones" not in new.to_dict()
    with pytest.raises(ValueError):
        read_result({**new.to_dict(), "contract_version": "1.0"})


def test_batch_reprocesamiento_explicito_preserva_legado(tmp_path):
    from pdfsum.adapters.job_store import FileJobStore
    from pdfsum.queue import JobQueue

    source = tmp_path / "entrada"
    source.mkdir()
    (source / "doc.txt").write_text(SOURCE)
    output = tmp_path / "salida"
    output.mkdir()
    old = SummaryResult("doc", "es", "articulo", "A", {"objetivo": BODY})
    JobQueue(FileJobStore(str(output / "_jobs.json"))).submit(
        "doc", SOURCE, lambda *_: old.to_dict()
    )
    generator = Mock(spec=TextGenerator)
    run_batch(str(source), str(output), generator)
    assert json.loads((output / "doc.json").read_text())["contract_version"] == "1.0"
    run_batch(str(source), str(output), generator, reprocess=True)
    assert json.loads((output / "doc.json").read_text())["contract_version"] == "2.0"
    generator.generate_abstract.assert_not_called()


def test_defaults_cli_y_vlm(monkeypatch):
    from pdfsum.adapters.vlm_ocr import resolve_vlm_model

    with patch("pdfsum.config.load_config", return_value={}):
        args = build_parser().parse_args(["summarize", "--text", "documento.txt"])
        assert args.long_strategy == "hierarchical"
        assert args.max_chars == 42000
        assert resolve_vlm_model(None) == "qwen3-vl:8b-instruct"
        monkeypatch.setenv("PDFSUM_VLM_MODEL", "visual-entorno")
        assert resolve_vlm_model(None) == "visual-entorno"
        assert resolve_vlm_model("visual-cli") == "visual-cli"


def test_extraccion_multilingue_preserva_orden_y_repeticiones(tmp_path):
    from tests.test_abstract_extraction import _EN

    english = _EN
    source = SOURCE + "\n\nABSTRACT\n" + english + "\n\nRESUMEN\n" + BODY
    (tmp_path / "doc.txt").write_text(source)
    generator = Mock(spec=TextGenerator)
    report = run_batch(
        str(tmp_path),
        str(tmp_path / "salida"),
        generator,
        abstract_llm=FakeSummarizer(),
    )
    record = json.loads((tmp_path / "salida/doc.json").read_text())
    assert [a["lang"] for a in record["ai_extracted_abstract"]] == ["es", "en", "es"]
    assert [a["text"] for a in record["ai_extracted_abstract"]] == [BODY, english, BODY]
    assert report["metrics"]["abstracts_extraidos"] == 3
    generator.generate_abstract.assert_not_called()


def test_excerpt_no_prioriza_abstract():
    from pdfsum.contract import DocType
    from pdfsum.excerpt import select_excerpt

    text = (
        SOURCE * 20
        + "\nINTRODUCCIÓN\n"
        + "Contexto. " * 80
        + "\nCONCLUSIONES\n"
        + "Hallazgos. " * 80
    )
    excerpt = select_excerpt(text, DocType.ARTICULO, 200, include_abstract=False)
    assert excerpt.parts == ["introducao", "conclusao"]
    assert BODY not in excerpt.text
    assert excerpt.truncated


def test_bloques_no_duplican_buffer_antes_de_parrafo_grande():
    from pdfsum.chunking import split_blocks

    text = "Prefacio\n\n" + "X" * 200 + "\n\nFinal"
    blocks = split_blocks(text, 100)
    assert "".join("".join(blocks).split()) == "".join(text.split())
    assert all(len(b) <= 100 for b in blocks)


def test_alias_model_no_configura_ambas_responsabilidades():
    from pdfsum.cli import _task_model

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("pdfsum.config.load_config", return_value={}),
    ):
        parser = build_parser()
        args = parser.parse_args(
            ["run", "--in", "entrada", "--workspace", "salida", "--model", "generador"]
        )
        assert _task_model(args, "summary")[1] == "generador"
        assert _task_model(args, "abstract")[1] == "qwen2.5:7b"
        args = parser.parse_args(
            [
                "extract-abstracts",
                "--in",
                "entrada",
                "--workspace",
                "salida",
                "--model",
                "revisor",
            ]
        )
        assert _task_model(args, "abstract")[1] == "revisor"
        assert _task_model(args, "summary")[1] == "qwen3:8b"


def test_doctor_separa_modelos_sin_inferir_por_nombre():
    from pdfsum.adapters.doctor import capabilities, check_task_models

    with patch(
        "pdfsum.adapters.doctor._ollama_models",
        return_value=["revision:7b", "vision:8b"],
    ):
        checks = check_task_models(
            "ollama", "revision:7b", "generacion:8b", "vision:8b"
        )
    caps = capabilities(checks)
    assert caps["abstract"]
    assert not caps["summary"]
    assert caps["vlm"]
    with patch("pdfsum.adapters.doctor._ollama_models", return_value=["qwen3:8b-otro"]):
        checks = check_task_models("ollama", "qwen3:8b", "qwen3:8b", "qwen3:8b")
    assert not any(c.ok for c in checks)


def test_debug_ventanas_no_sobrescribe_intentos(tmp_path):
    from pdfsum.adapters.abstract_refine_debug import AbstractRefineDebugSink

    text = SOURCE + "\n" + "Contenido. " * 100 + "\n" + SOURCE
    result = extract_refined_abstracts(
        text, FakeSummarizer(), 250, debug_sink=AbstractRefineDebugSink(tmp_path, "doc")
    )
    assert result.refinement_succeeded
    responses = list((tmp_path / "doc").glob("*-response.txt"))
    assert len(responses) >= 2
    assert len(responses) == len(list((tmp_path / "doc").glob("*-validation.json")))


def test_api_y_worker_entregan_nuevo_contrato_y_preservan_cache(tmp_path):
    from fastapi.testclient import TestClient

    from pdfsum.adapters.api_service import create_app
    from pdfsum.adapters.service_worker import run_once

    client = TestClient(create_app(tmp_path, token="secreto"))
    headers = {"Authorization": "Bearer secreto"}
    response = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    transcriber = FakeTranscriber(SOURCE)
    generator = Mock(spec=TextGenerator)
    assert run_once(tmp_path, transcriber, generator) == 1
    job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    record = client.get(job["summary_url"], headers=headers).json()
    assert record["contract_version"] == "2.0"
    assert record["ai_extracted_abstract"][0]["text"] == BODY
    assert job["status"] == "done"
    with patch.object(
        transcriber, "transcribe", side_effect=AssertionError("OCR repetido")
    ):
        assert run_once(tmp_path, transcriber, generator, reprocess=True) == 1
    generator.generate_abstract.assert_not_called()


def test_worker_fallo_generacion_no_marca_done(tmp_path):
    from fastapi.testclient import TestClient

    from pdfsum.adapters.api_service import create_app
    from pdfsum.adapters.service_worker import run_once

    client = TestClient(create_app(tmp_path, token="secreto"))
    headers = {"Authorization": "Bearer secreto"}
    response = client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
    )
    job_id = response.json()["job_id"]
    generator = Mock(spec=TextGenerator)
    generator.generate_abstract.side_effect = RuntimeError("Modelo ausente")
    run_once(tmp_path, FakeTranscriber("Contenido sin resumen."), generator)
    job = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    assert job["status"] == "failed"
    assert not list((tmp_path / "summaries").glob("doc*.json"))
