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


@pytest.mark.parametrize(
    "raw,etapa,tipo,mensaje",
    [
        (
            TimeoutError("conexión agotada"),
            "llamada_llm",
            "TimeoutError",
            "conexión agotada",
        ),
        ("JSON roto", "validacion", "JSONDecodeError", "Expecting value"),
        (
            respuesta([Abstract("en", "RESUMEN", BODY)]),
            "validacion",
            "ValueError",
            "Idioma incompatible con el encabezado",
        ),
    ],
)
def test_eventos_fallo_y_metricas(tmp_path, caplog, raw, etapa, tipo, mensaje):
    ws = Workspace(tmp_path / "salida", logs_dir=tmp_path / "logs")
    for name in ("a", "b", "c"):
        (tmp_path / f"{name}.pdf").touch()
    llm = Mock(spec=TextLLM)
    llm.complete_json.side_effect = [
        raw,
        respuesta(extract_abstracts(SOURCE)),
        '{"abstracts": []}',
    ]
    report = extract_abstracts_from_pdfs(
        str(tmp_path),
        ws,
        FakeTranscriber(SOURCE),
        llm,
        backend="ollama",
        model="modelo-prueba",
    )
    assert report["metrics"] == {
        "revision_llm_exitosa": 2,
        "fallback_determinista": 1,
        "sin_abstract": 1,
    }
    records = [
        json.loads(line)
        for line in (ws.logs_dir / "events.jsonl").read_text().splitlines()
    ]
    assert len({r["run_id"] for r in records}) == 1
    assert all(r["timestamp"] for r in records)
    events = [r for r in records if r.get("doc_id") == "a"]
    start = next(r for r in events if r["event"] == "abstract_refine_started")
    end = next(r for r in events if r["event"] == "abstract_refine_completed")
    assert start["backend"] == "ollama"
    assert start["model"] == "modelo-prueba"
    assert start["candidate_count"] == 1
    assert end["context_chars"] == len(SOURCE)
    assert end["prompt_chars"] == len(llm.complete_json.call_args_list[0].args[0])
    assert end["failure_phase"] == etapa
    assert end["error_type"] == tipo
    assert mensaje in end["error"]
    assert mensaje in caplog.text
    assert end["fallback"] is True
    assert end["accepted_count"] == 0
    assert end["final_count"] == 1
    assert end["seconds"] >= 0
    assert any(r["event"] == "phase_failed" and r["phase"] == etapa for r in events)
    persisted = json.loads(ws.report_path.read_text())
    assert persisted["metrics"] == report["metrics"]
    assert "abstracts" not in persisted["documents"][0]
    assert records[-1]["metrics"] == report["metrics"]
    success = next(
        r
        for r in records
        if r.get("doc_id") == "b" and r["event"] == "abstract_refine_completed"
    )
    assert success["accepted_count"] == success["final_count"] == 1
    assert success["fallback"] is False
    assert any(
        r["event"] == "phase_completed"
        and r.get("phase") == "llamada_llm"
        and r["seconds"] >= 0
        for r in records
    )
    assert set(json.loads(ws.abstract_path("a").read_text())) == {
        "doc_id",
        "status",
        "source_kind",
        "abstracts",
    }
    for path in (ws.report_path, ws.logs_dir / "events.jsonl"):
        content = path.read_text()
        assert BODY not in content
        assert "JSON roto" not in content
        assert "Eres un extractor" not in content


@pytest.mark.parametrize("limit", [20, 20_000])
def test_contexto_real_y_revision_exitosa(tmp_path, limit):
    ws = Workspace(tmp_path / "salida")
    (tmp_path / "a.pdf").touch()
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = '{"abstracts": []}'
    report = extract_abstracts_from_pdfs(
        str(tmp_path), ws, FakeTranscriber(SOURCE), llm, limit
    )
    events = [
        json.loads(line)
        for line in (ws.report_path.parent / "events.jsonl").read_text().splitlines()
    ]
    end = next(r for r in events if r["event"] == "abstract_refine_completed")
    assert end["context_chars"] == min(limit, len(SOURCE))
    assert end["prompt_chars"] == len(llm.complete_json.call_args.args[0])
    assert end["accepted_count"] == 0
    assert end["fallback"] is False
    assert "error" not in end
    assert report["metrics"]["revision_llm_exitosa"] == 1
    assert report["metrics"]["sin_abstract"] == 1


def test_lote_vacio_registra_resumen(tmp_path):
    ws = Workspace(tmp_path / "salida")
    report = extract_abstracts_from_pdfs(
        str(tmp_path), ws, FakeTranscriber(""), FakeSummarizer()
    )
    assert report["total"] == 0
    assert all(value == 0 for value in report["metrics"].values())
    assert json.loads(ws.report_path.read_text())["metrics"] == report["metrics"]


def test_fallo_preparacion_conserva_cache(tmp_path):
    ws = Workspace(tmp_path / "salida")
    ws.ocr_dir.mkdir(parents=True)
    ws.ocr_path("a").write_text(SOURCE)
    (tmp_path / "a.pdf").touch()
    transcriber = Mock()
    llm = Mock(spec=TextLLM)
    report = extract_abstracts_from_pdfs(str(tmp_path), ws, transcriber, llm, 0)
    transcriber.transcribe.assert_not_called()
    llm.complete_json.assert_not_called()
    assert report["metrics"]["fallback_determinista"] == 1
    events = [
        json.loads(line)
        for line in (ws.report_path.parent / "events.jsonl").read_text().splitlines()
    ]
    end = next(r for r in events if r["event"] == "abstract_refine_completed")
    assert end["failure_phase"] == "preparacion_revision"
    assert end["source_kind"] == "cached"
    assert end["final_count"] == 1


@pytest.mark.parametrize(
    "original,corregido",
    [
        (
            "Este estudio evaluó pacientes REVISTA DE SALUD VOL. 12 2020 y observó resultados favorables en la comunidad.",
            "Este estudio evaluó pacientes y observó resultados favorables en la comunidad.",
        ),
        (
            "Este estudio evaluó pacientes 23 y observó resultados favorables en la comunidad.",
            "Este estudio evaluó pacientes y observó resultados favorables en la comunidad.",
        ),
        (
            "Este estudio evaluó la c0munidad y observó resultados favorables entre todos los participantes.",
            "Este estudio evaluó la comunidad y observó resultados favorables entre todos los participantes.",
        ),
        (
            "Este estudio, describe los resultados.",
            "Este estudio describe los resultados.",
        ),
        (
            "Este   estudio\n describe los resultados.",
            "Este estudio describe los resultados.",
        ),
    ],
)
def test_anclaje_aproximado_acepta_ruido(original, corregido):
    expected = [Abstract("es", "RESUMEN", corregido)]
    events = []
    assert (
        refine_abstracts(
            "RESUMEN\n" + original,
            [],
            FakeSummarizer(respuesta(expected)),
            event_sink=lambda event, **fields: events.append((event, fields)),
        )
        == expected
    )
    metric = next(
        fields for event, fields in events if event == "abstract_refine_validation"
    )
    assert metric["coverage"] == 1
    assert metric["supported_percent"] == 100
    assert metric["evaluated_tokens"] > 0
    assert metric["validation_method"] == (
        "exact" if "   " in original else "approximate"
    )
    assert original not in json.dumps(events)
    assert corregido not in json.dumps(events)


@pytest.mark.parametrize(
    "original,propuesta",
    [
        (
            "La vacunación presentó buenos resultados entre los participantes.",
            "La inmunización tuvo efectos positivos entre las personas estudiadas.",
        ),
        (
            "La vacunación presentó buenos resultados entre los participantes.",
            "La vacunación redujo la mortalidad en 75% entre los participantes.",
        ),
        (BODY, BODY + " Se concluye que la mortalidad desaparecerá."),
        (
            BODY,
            BODY + " El hospital de La Habana incorporó tratamientos experimentales.",
        ),
        (
            "La intervención no redujo la mortalidad en los pacientes.",
            "La intervención redujo la mortalidad en los pacientes.",
        ),
        (
            "Los pacientes recibieron 12 dosis durante el estudio comunitario.",
            "Los pacientes recibieron 13 dosis durante el estudio comunitario.",
        ),
        (BODY, BODY.replace("resultados", "hallazgos")),
        (BODY, "This study describes the results of a community intervention."),
    ],
)
def test_rechaza_contenido_nuevo_aunque_sea_semanticamente_parecido(
    original, propuesta
):
    events = []
    with pytest.raises(ValueError, match="Texto del resumen sin respaldo"):
        refine_abstracts(
            "RESUMEN\n" + original,
            [],
            FakeSummarizer(respuesta([Abstract("es", "RESUMEN", propuesta)])),
            event_sink=lambda event, **fields: events.append((event, fields)),
        )
    metric = events[-1][1]
    assert metric["validation_method"] == "approximate"
    assert (
        metric["rejection_reason"]
        == "Texto del resumen sin respaldo en la transcripción"
    )
    assert metric["rejection_detail"]
    assert propuesta not in json.dumps(events)


def test_recorte_grande_no_depende_del_candidato():
    context = "RESUMEN\n" + BODY + "\nINTRODUCCIÓN\n" + "Texto posterior. " * 200
    expected = [Abstract("es", "RESUMEN", BODY)]
    assert (
        refine_abstracts(
            context,
            [Abstract("es", "RESUMEN", context)],
            FakeSummarizer(respuesta(expected)),
        )
        == expected
    )


def test_no_extrae_introduccion_ni_cruza_bloques():
    for context, expected in [
        (
            "RESUMEN\n"
            + BODY
            + "\nINTRODUCCIÓN\nLa investigación estudió otra población.",
            [Abstract("es", "RESUMEN", "La investigación estudió otra población.")],
        ),
        (
            "RESUMEN\n" + BODY + "\nABSTRACT\nEnglish text.",
            [
                Abstract("en", "ABSTRACT", "English text."),
                Abstract("es", "RESUMEN", BODY),
            ],
        ),
        (
            "RESUMEN\n" + BODY + "\nABSTRACT\nEnglish text.",
            [Abstract("es", "RESUMEN", BODY + " English text.")],
        ),
    ]:
        with pytest.raises(ValueError):
            refine_abstracts(context, [], FakeSummarizer(respuesta(expected)))


def test_keywords_se_recuperan_tras_anclaje_aproximado():
    original = "Este estudio evaluó pacientes 23 y observó resultados favorables en la comunidad."
    corrected = original.replace(" 23", "")
    context = "RESUMEN\n" + original + "\nPalabras clave: salud; comunidad."
    expected = [Abstract("es", "RESUMEN", corrected, "salud; comunidad.")]
    assert (
        refine_abstracts(
            context,
            extract_abstracts(context),
            FakeSummarizer(respuesta([Abstract("es", "RESUMEN", corrected)])),
        )
        == expected
    )


def test_metricas_aproximadas_se_persisten_sin_texto(tmp_path):
    context = "RESUMEN\nEste estudio evaluó pacientes 23 y observó resultados favorables en la comunidad."
    corrected = context.split("\n")[1].replace(" 23", "")
    (tmp_path / "a.pdf").touch()
    ws = Workspace(tmp_path / "salida", logs_dir=tmp_path / "logs")
    extract_abstracts_from_pdfs(
        str(tmp_path),
        ws,
        FakeTranscriber(context),
        FakeSummarizer(respuesta([Abstract("es", "RESUMEN", corrected)])),
    )
    content = (ws.logs_dir / "events.jsonl").read_text()
    events = [json.loads(line) for line in content.splitlines()]
    metric = next(e for e in events if e["event"] == "abstract_refine_validation")
    assert metric["validation_method"] == "approximate"
    assert metric["coverage"] == 1
    assert corrected not in content
    assert context not in content
    assert (
        sum(
            e["event"] == "phase_completed" and e["phase"] == "validacion"
            for e in events
        )
        == 1
    )


@pytest.mark.parametrize(
    "abstract,context,motivo",
    [
        (Abstract("es", "RESUMEN", ""), SOURCE, "Resumen vacío"),
        (
            Abstract("en", "RESUMEN", BODY),
            SOURCE,
            "Idioma incompatible con el encabezado",
        ),
        (
            Abstract("es", "RESUMEN", BODY + " Palabras clave: salud"),
            SOURCE,
            "Palabras clave mezcladas dentro del resumen",
        ),
        (Abstract("es", "RESUMEN", BODY), BODY, "Encabezado sin respaldo"),
        (
            Abstract("es", "RESUMEN", BODY, "inventadas"),
            SOURCE,
            "Palabras clave sin respaldo",
        ),
    ],
)
def test_motivos_de_rechazo_separados(abstract, context, motivo):
    with pytest.raises(ValueError, match=motivo):
        refine_abstracts(context, [], FakeSummarizer(respuesta([abstract])))


def test_una_palabra_inventada_no_se_diluye_en_resumen_largo():
    original = BODY * 40
    propuesta = original + " Mortalidad."
    with pytest.raises(ValueError, match="Texto del resumen sin respaldo"):
        refine_abstracts(
            "RESUMEN\n" + original,
            [],
            FakeSummarizer(respuesta([Abstract("es", "RESUMEN", propuesta)])),
        )


def test_rechaza_numero_decimal_o_porcentaje_modificado():
    for original, propuesta in [("12,5", "12,6"), ("12%", "12"), ("-12", "12")]:
        source = (
            f"El resultado fue {original} entre todos los participantes del estudio."
        )
        output = (
            f"El resultado fue {propuesta} entre todos los participantes del estudio."
        )
        with pytest.raises(ValueError, match="Texto del resumen sin respaldo"):
            refine_abstracts(
                "RESUMEN\n" + source,
                [],
                FakeSummarizer(respuesta([Abstract("es", "RESUMEN", output)])),
            )
