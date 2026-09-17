"""Política compartida e integración sin servicios externos."""

import json
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest

from pdfsum.abstract_extraction import extract_refined_abstracts
from pdfsum.abstracts import extract_abstracts
from pdfsum.adapters.batch_runner import run_batch
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.adapters.pdf_batch import run_batch_pdfs
from pdfsum.contract import Abstract, TextLLM
from pdfsum.pipeline import summarize_document
from pdfsum.workspace import Workspace

SOURCE = "RESUMEN\nEste estudio evaluó la atención comunitaria y sus resultados."


def test_revision_exitosa_y_eventos():
    expected = extract_abstracts(SOURCE)
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = json.dumps(
        {"abstracts": [asdict(a) for a in expected]}
    )
    sink = Mock()
    result = extract_refined_abstracts(SOURCE, llm, event_sink=sink)
    assert result.candidate_count == 1
    assert result.abstracts == expected
    assert result.refinement_attempted
    assert result.refinement_succeeded
    assert result.error is None
    assert any(c.args[0] == "abstract_refine_validation" for c in sink.call_args_list)


def test_fallo_conserva_candidatos_y_excepcion():
    llm = Mock(spec=TextLLM)
    error = TimeoutError("Tiempo de espera agotado")
    llm.complete_json.side_effect = error
    result = extract_refined_abstracts(SOURCE, llm)
    assert result.abstracts == extract_abstracts(SOURCE)
    assert result.candidate_count == 1
    assert result.refinement_attempted
    assert not result.refinement_succeeded
    assert result.error is error


def test_recupera_sin_candidatos():
    expected = extract_abstracts(SOURCE)
    llm = FakeSummarizer(json.dumps({"abstracts": [asdict(a) for a in expected]}))
    with patch("pdfsum.abstract_extraction.extract_abstracts", return_value=[]):
        result = extract_refined_abstracts(SOURCE, llm)
    assert result.candidate_count == 0
    assert result.refinement_succeeded
    assert result.abstracts == expected


def test_sin_llm_no_revisa():
    with patch("pdfsum.abstract_extraction.refine_abstracts") as refine:
        result = extract_refined_abstracts(SOURCE, None)
    refine.assert_not_called()
    assert result.abstracts == extract_abstracts(SOURCE)
    assert result.candidate_count == 1
    assert not result.refinement_attempted
    assert not result.refinement_succeeded
    assert result.error is None


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_interrupciones_se_propagan(error):
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = error
    with pytest.raises(type(error)):
        extract_refined_abstracts(SOURCE, llm)


@pytest.mark.parametrize(
    "provided", [[], [Abstract("es", "RESUMEN", "Texto original")]]
)
def test_pipeline_respeta_lista_inyectada(provided):
    with patch("pdfsum.pipeline.extract_abstracts") as extract:
        result = summarize_document("doc", SOURCE, FakeSummarizer(), abstracts=provided)
    extract.assert_not_called()
    assert result.abstracts_origem is provided
    assert result.idiomas_resumo_origem == (["es"] if provided else [])


def test_pipeline_legacy_extrae():
    with patch("pdfsum.pipeline.extract_abstracts", wraps=extract_abstracts) as extract:
        result = summarize_document("doc", SOURCE, FakeSummarizer())
    extract.assert_called_once_with(SOURCE)
    assert result.abstracts_origem == extract_abstracts(SOURCE)


def test_pdf_revisa_crudo_y_resume_limpio(tmp_path):
    (tmp_path / "doc.pdf").touch()
    ws = Workspace(tmp_path / "salida")
    llm = FakeSummarizer()
    cleaned = "Texto limpio para generar el resumen estructurado."
    with (
        patch("pdfsum.adapters.pdf_batch.clean_text", return_value=cleaned),
        patch(
            "pdfsum.adapters.pdf_batch.extract_refined_abstracts",
            wraps=extract_refined_abstracts,
        ) as extract,
        patch(
            "pdfsum.adapters.pdf_batch.summarize_document", wraps=summarize_document
        ) as summary,
    ):
        report = run_batch_pdfs(
            str(tmp_path),
            ws,
            FakeTranscriber(SOURCE),
            llm,
            abstract_llm=llm,
            abstract_refine_context_chars=1234,
        )
    assert report["status"] == "completed"
    assert extract.call_args.args == (SOURCE, llm, 1234)
    assert summary.call_args.kwargs["text"] == cleaned
    assert summary.call_args.kwargs["abstracts"] == extract_abstracts(SOURCE)
    assert "abstracts" in report["documents"][0]["tiempos_por_fase"]


def test_pdf_fallo_revision_continua_qa_y_persistencia(tmp_path, caplog):
    (tmp_path / "doc.pdf").touch()
    ws = Workspace(tmp_path / "salida")
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = TimeoutError("Revisión demorada")
    report = run_batch_pdfs(
        str(tmp_path), ws, FakeTranscriber(SOURCE), FakeSummarizer(), abstract_llm=llm
    )
    assert report["status"] == "completed"
    record = json.loads(ws.summary_path("doc").read_text())
    assert record["abstracts_origem"] == [asdict(a) for a in extract_abstracts(SOURCE)]
    assert "_qa" in record
    assert "Revisión demorada" in caplog.text


@pytest.mark.parametrize("failure", [False, True])
def test_batch_cache_incluye_revision(tmp_path, failure):
    (tmp_path / "doc.txt").write_text(SOURCE)
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = '{"abstracts": []}'
    if failure:
        llm.complete_json.side_effect = TimeoutError("Revisión demorada")
    for _ in range(2):
        report = run_batch(
            str(tmp_path),
            str(tmp_path / "salida"),
            FakeSummarizer(),
            abstract_llm=llm,
            abstract_refine_context_chars=1234,
        )
        assert report["status"] == "completed"
    llm.complete_json.assert_called_once()
    assert report["documents"][0]["cache_hit"]
    record = json.loads((tmp_path / "salida/doc.json").read_text())
    expected = extract_abstracts(SOURCE) if failure else []
    assert record["abstracts_origem"] == [asdict(a) for a in expected]


@pytest.mark.parametrize(
    "command", ["summarize", "batch", "run", "extract-abstracts", "verify", "worker"]
)
def test_cli_propaga_llm_y_limite(tmp_path, command):
    from pdfsum.cli import main

    source = tmp_path / "doc.txt"
    transcription = SOURCE + "\nINTRODUCCIÓN\n" + "Contenido del documento. " * 100
    source.write_text(transcription)
    (tmp_path / "doc.pdf").touch()
    output = tmp_path / "salida"
    llm = FakeSummarizer()
    args = {
        "summarize": ["--text", str(source), "--dry-run"],
        "batch": ["--in", str(tmp_path), "--out", str(output), "--dry-run"],
        "run": ["--in", str(tmp_path), "--workspace", str(output), "--fake"],
        "extract-abstracts": [
            "--in",
            str(tmp_path),
            "--workspace",
            str(output),
            "--fake",
        ],
        "verify": ["--pdfs", str(tmp_path), "--workspace", str(output), "--fake"],
        "worker": ["--workspace", str(output), "--fake"],
    }
    with (
        patch(
            "pdfsum.config.load_config",
            return_value={"abstract_refine_context_chars": 1234},
        ),
        patch("pdfsum.cli._build_summarizer", return_value=llm),
        patch(
            "pdfsum.cli._build_transcriber", return_value=FakeTranscriber(transcription)
        ),
        patch.object(llm, "complete_json", wraps=llm.complete_json) as complete,
        patch("pdfsum.acceptance.load_control_set", return_value=[]),
        patch("pdfsum.adapters.service_worker.main_loop") as loop,
    ):
        main([command, *args[command]])
    if command == "worker":
        assert loop.call_args.kwargs["abstract_llm"] is llm
        assert loop.call_args.kwargs["abstract_refine_context_chars"] == 1234
    else:
        complete.assert_called_once()
        data = json.loads(complete.call_args.args[0].splitlines()[-1])
        assert data["transcription"] == transcription[:1234]


@pytest.mark.parametrize("limit", [0, -1, True, "100", 1.5, None])
def test_config_rechaza_limite_invalido(limit):
    from pdfsum.config import resolve_abstract_refine_context_chars

    with (
        patch(
            "pdfsum.config.load_config",
            return_value={"abstract_refine_context_chars": limit},
        ),
        pytest.raises(ValueError, match="entero positivo"),
    ):
        resolve_abstract_refine_context_chars()


def test_worker_loop_propaga_revision(tmp_path):
    from pdfsum.adapters.service_worker import main_loop

    llm = FakeSummarizer()
    transcriber = FakeTranscriber(SOURCE)
    with (
        patch(
            "pdfsum.adapters.service_worker.run_once", side_effect=KeyboardInterrupt
        ) as once,
        pytest.raises(KeyboardInterrupt),
    ):
        main_loop(
            tmp_path,
            transcriber,
            llm,
            abstract_llm=llm,
            abstract_refine_context_chars=1234,
        )
    assert once.call_args.kwargs["abstract_llm"] is llm
    assert once.call_args.kwargs["abstract_refine_context_chars"] == 1234


def test_worker_procesa_revision_dentro_del_job(tmp_path):
    import hashlib

    from pdfsum.adapters.job_store import DirJobStore
    from pdfsum.adapters.service_worker import run_once
    from pdfsum.queue import Job, job_key

    pdf_dir = tmp_path / "inbox/doc"
    pdf_dir.mkdir(parents=True)
    content = b"%PDF-1.4"
    (pdf_dir / "doc.pdf").write_bytes(content)
    store = DirJobStore(tmp_path / "service_jobs")
    key = job_key("doc", hashlib.sha256(content).hexdigest())
    store.put(key, Job(key=key, doc_id="doc").to_dict())
    llm = FakeSummarizer()
    with patch.object(llm, "complete_json", wraps=llm.complete_json) as complete:
        for _ in range(2):
            run_once(
                tmp_path,
                FakeTranscriber(SOURCE),
                llm,
                abstract_llm=llm,
                abstract_refine_context_chars=20,
            )
    complete.assert_called_once()
    assert (
        json.loads(complete.call_args.args[0].splitlines()[-1])["transcription"]
        == SOURCE[:20]
    )
    assert store.get(key)["state"] == "done"
