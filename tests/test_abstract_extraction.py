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


@pytest.mark.parametrize("respuesta", [TimeoutError("Sin conexión"), "JSON inválido"])
def test_fallback_descarta_contaminacion_y_conserva_buen_candidato(respuesta):
    contexto = (
        SOURCE + "\nPalabras clave: salud.\n\nAbstract\n343\nOriginal Paper\n"
        "John Doe*\nINTRODUCTION\nThis is the introduction of the full article."
    )
    llm = Mock(spec=TextLLM)
    if isinstance(respuesta, Exception):
        llm.complete_json.side_effect = respuesta
    else:
        llm.complete_json.return_value = respuesta
    result = extract_refined_abstracts(contexto, llm)
    assert result.candidate_count == 2
    assert len(result.abstracts) == 1
    assert result.abstracts[0].lang == "es"
    assert result.discarded_candidates == 1
    diagnostico = result.diagnostics()
    assert diagnostico["fallback"]
    assert diagnostico["fallback_reason"]
    assert diagnostico["failure_phase"] == (
        "llamada_llm" if isinstance(respuesta, Exception) else "validacion"
    )


def test_fallback_puede_quedar_sin_resumen():
    contexto = "Abstract\n625 Journal Name - 2017;41(4):625-632 John Doe John Doe"
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = TimeoutError("Sin conexión")
    result = extract_refined_abstracts(contexto, llm)
    assert result.abstracts == []
    assert result.discarded_candidates == result.candidate_count == 1


@pytest.mark.parametrize("revisar", [False, True])
def test_report_pdf_distingue_ejecucion_y_revision(tmp_path, revisar):
    (tmp_path / "doc.pdf").touch()
    ws = Workspace(tmp_path / "salida")
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = TimeoutError("Revisión demorada")
    report = run_batch_pdfs(
        str(tmp_path),
        ws,
        FakeTranscriber(SOURCE),
        FakeSummarizer(),
        abstract_llm=llm if revisar else None,
    )
    assert report["status"] == "completed"
    diagnostico = report["documents"][0]["abstract_extraction"]
    assert diagnostico["refinement_attempted"] is revisar
    assert diagnostico["fallback"] is revisar
    assert not diagnostico["refinement_succeeded"]
    assert diagnostico["candidate_count"] == diagnostico["final_count"] == 1
    persistido = json.loads(ws.report_path.read_text())
    assert persistido["documents"][0]["abstract_extraction"] == diagnostico
    resultado = json.loads(ws.summary_path("doc").read_text())
    assert resultado["meta"]["abstract_extraction"] == diagnostico


def test_fallback_conserva_resumen_que_empieza_con_cifra_clinica():
    contexto = (
        "RESUMEN\n100 pacientes participaron en el estudio de atención comunitaria."
    )
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = TimeoutError("Sin conexión")
    resultado = extract_refined_abstracts(contexto, llm)
    assert resultado.abstracts == extract_abstracts(contexto)
    assert resultado.discarded_candidates == 0


# Transcripciones multilingües simuladas, sin excepciones por documento.
_EN = "The study evaluated the health of patients and the results supported clinical monitoring."
_PT = "O estudo avaliou a saúde dos pacientes com resultados importantes para a comunidade."
_BILINGUE = (
    _EN
    + "\n\nKeywords: Health. Study.\n\nResumo\n"
    + _PT
    + "\n\nPalavras-chave: Saúde. Estudo.\n\nDOI: 10.1234/567\n\n"
    "Abstract\n617\nArtigo Original\nAutores\n\nINTRODUCTION\nArticle body."
)


def _salida(lang, header, texto):
    return json.dumps({"abstracts": [asdict(Abstract(lang, header, texto))]})


def test_n_complementa_sin_modificar_resumen_validado():
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [
        _salida("pt", "RESUMO", _PT),
        _salida("en", "ABSTRACT", _EN),
    ]
    result = extract_refined_abstracts(_BILINGUE, llm)
    assert [a.text for a in result.abstracts] == [_EN, _PT]
    assert llm.complete_json.call_count == 2
    prompt = llm.complete_json.call_args.args[0]
    datos = json.loads(prompt.splitlines()[-1])
    assert datos["validated_languages"] == ["pt"]
    assert datos["target_lang"] == "en"
    assert datos["transcription_fragments"] == [_EN]
    assert "encabezado original" not in prompt
    ejemplo = json.loads(prompt.split("Devuelve SOLO JSON: ")[1].splitlines()[0][:-1])
    assert ejemplo["abstracts"][0]["header"] == datos["source_headers"][0]
    assert datos["source_headers"] == ["Abstract"]
    assert ejemplo["abstracts"][0]["keywords"] == ""
    assert (
        "Copia header exactamente de source_headers, sin inventarlo, traducirlo "
        "ni sustituirlo."
    ) in prompt
    assert (
        "Devuelve keywords solo si están literalmente disponibles en los "
        'fragmentos proporcionados; en caso contrario, usa "".'
    ) in prompt
    assert _PT not in prompt
    assert datos["missing_abstract_evidence"][0]["lang"] == "en"
    diagnostico = result.diagnostics()
    assert diagnostico["refinement_succeeded"]
    assert diagnostico["completion_checked"]
    assert diagnostico["completion_succeeded"]
    assert diagnostico["completion_retry_attempted"]
    assert diagnostico["completion_retry_succeeded"]
    assert diagnostico["missing_abstract_evidence"] == []
    assert not diagnostico["fallback"]


@pytest.mark.parametrize(
    "segunda",
    [
        _salida(
            "en", "ABSTRACT", "The invented study recruited 150 imaginary patients."
        ),
        _salida("pt", "RESUMO", _PT),
        '{"abstracts": []}',
        "JSON inválido",
        TimeoutError("Sin conexión"),
    ],
)
def test_o_fallo_complementario_conserva_primera_revision(segunda):
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [_salida("pt", "RESUMO", _PT), segunda]
    result = extract_refined_abstracts(_BILINGUE, llm)
    assert [a.text for a in result.abstracts] == [_PT]
    assert llm.complete_json.call_count == 2
    diagnostico = result.diagnostics()
    assert diagnostico["refinement_succeeded"]
    assert diagnostico["completion_checked"]
    assert diagnostico["completion_retry_attempted"]
    assert not diagnostico["completion_succeeded"]
    assert not diagnostico["completion_retry_succeeded"]
    assert diagnostico["missing_abstract_evidence"][0]["lang"] == "en"
    assert not diagnostico["fallback"]
    assert result.error is None


@pytest.mark.parametrize("adaptador", ["abstracts", "pdf", "batch"])
def test_completitud_parcial_se_persiste_en_report_y_meta(tmp_path, adaptador):
    from pdfsum.adapters.abstract_batch import extract_abstracts_from_pdfs

    (tmp_path / "doc.pdf").touch()
    (tmp_path / "doc.txt").write_text(_BILINGUE)
    ws = Workspace(tmp_path / "salida", logs_dir=tmp_path / "logs")
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [
        _salida("pt", "RESUMO", _PT),
        TimeoutError("Sin conexión"),
    ]
    if adaptador == "abstracts":
        report = extract_abstracts_from_pdfs(
            str(tmp_path), ws, FakeTranscriber(_BILINGUE), llm
        )
    elif adaptador == "pdf":
        report = run_batch_pdfs(
            str(tmp_path),
            ws,
            FakeTranscriber(_BILINGUE),
            FakeSummarizer(),
            abstract_llm=llm,
        )
    else:
        for _ in range(2):
            report = run_batch(
                str(tmp_path), str(ws.root), FakeSummarizer(), abstract_llm=llm
            )
        assert report["documents"][0]["cache_hit"]
    diagnostico = report["documents"][0]["abstract_extraction"]
    assert diagnostico["refinement_succeeded"]
    assert not diagnostico["completion_succeeded"]
    assert diagnostico["completion_retry_error_type"] == "TimeoutError"
    assert diagnostico["completion_retry_failure_phase"] == "llamada_complementaria"
    assert llm.complete_json.call_count == 2
    assert _PT not in json.dumps(diagnostico)
    if adaptador == "pdf":
        persistido = json.loads(ws.summary_path("doc").read_text())
        assert persistido["meta"]["abstract_extraction"] == diagnostico
    elif adaptador == "batch":
        persistido = json.loads((ws.root / "doc.json").read_text())
        assert persistido["meta"]["abstract_extraction"] == diagnostico


def test_p_keywords_del_cuerpo_no_activa_complemento():
    texto = SOURCE + "\nINTRODUCTION\n" + _EN + "\nKeywords: Health. Study.\nAbstract\n"
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = _salida("es", "RESUMEN", SOURCE.splitlines()[1])
    result = extract_refined_abstracts(texto, llm)
    llm.complete_json.assert_called_once()
    assert result.diagnostics()["completion_succeeded"]
    assert not result.diagnostics()["completion_retry_attempted"]


def test_respuesta_vacia_valida_tambien_comprueba_completitud():
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [
        '{"abstracts": []}',
        _salida("en", "ABSTRACT", _EN),
        '{"abstracts": []}',
    ]
    result = extract_refined_abstracts(_BILINGUE, llm)
    assert [a.text for a in result.abstracts] == [_EN]
    assert not result.diagnostics()["completion_succeeded"]
    assert result.diagnostics()["missing_abstract_evidence"][0]["lang"] == "pt"
    assert llm.complete_json.call_count == 3


def test_validacion_complementaria_registra_item_sin_texto():
    llm = Mock(spec=TextLLM)
    inventado = "The invented study recruited 150 imaginary patients."
    llm.complete_json.side_effect = [
        _salida("pt", "RESUMO", _PT),
        _salida("en", "ABSTRACT", inventado),
    ]
    eventos = []
    result = extract_refined_abstracts(
        _BILINGUE,
        llm,
        event_sink=lambda evento, **campos: eventos.append((evento, campos)),
    )
    metricas = [
        campos for evento, campos in eventos if evento == "abstract_refine_validation"
    ]
    assert [m["validation_attempt"] for m in metricas] == [1, 2]
    assert [m["abstract_index"] for m in metricas] == [0, 0]
    assert metricas[1]["abstract_lang"] == "en"
    assert metricas[1]["abstract_header"] == "ABSTRACT"
    assert metricas[1]["rejection_reason"]
    assert metricas[1]["span_start"] is None
    assert inventado not in json.dumps(eventos)
    assert (
        result.diagnostics()["completion_retry_failure_phase"]
        == "validacion_complementaria"
    )


@pytest.mark.parametrize(
    "propuesta",
    [
        _PT,
        "Article body.",
        _EN.replace("health", "wellbeing"),
        _EN.replace("the health of patients and ", ""),
    ],
)
def test_complemento_del_idioma_solicitado_conserva_validadores(propuesta):
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [
        _salida("pt", "RESUMO", _PT),
        _salida("en", "ABSTRACT", propuesta),
    ]
    eventos = []
    resultado = extract_refined_abstracts(
        _BILINGUE,
        llm,
        event_sink=lambda evento, **campos: eventos.append((evento, campos)),
    )
    assert [a.text for a in resultado.abstracts] == [_PT]
    assert not resultado.diagnostics()["completion_succeeded"]
    validaciones = [
        campos
        for evento, campos in eventos
        if evento == "abstract_refine_validation" and campos["validation_attempt"] == 2
    ]
    assert len(validaciones) == 1
    assert validaciones[0]["target_lang"] == "en"
    assert validaciones[0]["rejection_reason"]
    if propuesta == _PT:
        assert (
            validaciones[0]["rejection_reason"]
            == "Span de resumen reutilizado o superpuesto"
        )
