"""Diagnóstico opt-in sin cambios de resultados, prompts ni eventos."""

import json
import logging
from unittest.mock import Mock, patch

import pytest

from pdfsum.abstract_extraction import extract_refined_abstracts
from pdfsum.adapters.abstract_refine_debug import AbstractRefineDebugSink
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.cli import main
from pdfsum.contract import TextLLM
from tests.test_abstract_extraction import _BILINGUE, _EN, _PT, SOURCE, _salida


@pytest.mark.parametrize(
    "texto,respuestas",
    [
        (SOURCE, [_salida("es", "RESUMEN", SOURCE.splitlines()[1])]),
        (SOURCE, ['  {"abstracts": [\r\n  inválido sensible']),
        (
            _BILINGUE,
            [_salida("pt", "RESUMO", _PT), _salida("en", "ABSTRACT", _EN)],
        ),
        (
            _BILINGUE,
            [
                _salida("pt", "RESUMO", _PT),
                json.dumps(
                    {
                        "abstracts": [
                            {"lang": "pt", "header": "RESUMO", "text": _PT},
                            {"lang": "en", "header": "ABSTRACT", "text": _EN},
                        ]
                    },
                    ensure_ascii=False,
                    indent=3,
                ),
            ],
        ),
    ],
)
def test_cli_preserva_respuestas_y_comportamiento(tmp_path, caplog, texto, respuestas):
    caplog.set_level(logging.INFO)
    (tmp_path / "documento.pdf").touch()
    resultados = []
    llamadas = []
    eventos = []
    for activo in (False, True):
        salida = tmp_path / str(activo)
        debug = tmp_path / "diagnostico"
        llm = Mock(spec=TextLLM)
        crudas = [" \r\n" + r + "\r\n  " for r in respuestas]
        llm.complete_json.side_effect = crudas
        args = [
            "extract-abstracts",
            "--in",
            str(tmp_path),
            "--workspace",
            str(salida),
            "--fake",
        ]
        if activo:
            args.extend(["--abstract-refine-debug-dir", str(debug)])
        with (
            patch("pdfsum.cli._build_summarizer", return_value=llm),
            patch("pdfsum.cli._build_transcriber", return_value=FakeTranscriber(texto)),
        ):
            assert main(args) == 0
        llamadas.append(llm.complete_json.call_args_list)
        resultados.append((salida / "abstracts/documento.json").read_bytes())
        archivos_eventos = list(salida.rglob("events.jsonl"))
        assert len(archivos_eventos) == 1
        eventos.append(
            [
                {
                    k: v
                    for k, v in json.loads(line).items()
                    if k not in {"run_id", "timestamp", "seconds"}
                }
                for line in archivos_eventos[0].read_text().splitlines()
            ]
        )
        for archivo in [*archivos_eventos, *salida.rglob("report.json")]:
            contenido = archivo.read_text()
            for cruda in crudas:
                assert cruda not in contenido
            assert _PT not in contenido
            assert _EN not in contenido
            assert "inválido sensible" not in contenido
        assert "inválido sensible" not in caplog.text
        assert _PT not in caplog.text
        assert _EN not in caplog.text
        if not activo:
            assert not debug.exists()
            assert not list(salida.rglob("attempt-*"))
            continue
        carpeta = debug / "documento"
        assert len(list(carpeta.iterdir())) == len(crudas) * 2
        for intento, cruda in enumerate(crudas, 1):
            assert (
                carpeta / f"attempt-{intento}-response.txt"
            ).read_bytes() == cruda.encode("utf-8")
            datos = json.loads(
                (carpeta / f"attempt-{intento}-validation.json").read_text()
            )
            assert datos["doc_id"] == "documento"
            assert datos["attempt"] == intento
            if "inválido sensible" in cruda:
                assert datos["error_type"] == "JSONDecodeError"
                assert not datos["validation_succeeded"]
            else:
                cantidad = len(json.loads(cruda)["abstracts"])
                assert datos["abstracts_returned"] == cantidad
                assert datos["validation_succeeded"]
                if cantidad == 2:
                    assert datos["error_type"] == ""
                    assert len(datos["validation"]) == 2
                    assert datos["validation"][0]["abstract_lang"] == "pt"
                    assert (
                        datos["validation"][0]["rejection_reason"]
                        == "Idioma distinto del solicitado"
                    )
    assert resultados[0] == resultados[1]
    assert llamadas[0] == llamadas[1]
    assert eventos[0] == eventos[1]


@pytest.mark.parametrize("fallo", ["mkdir", "write_bytes", "write_text"])
@pytest.mark.parametrize("valida", [False, True])
def test_fallo_de_escritura_no_cambia_validacion(tmp_path, caplog, fallo, valida):
    respuesta = (
        _salida("es", "RESUMEN", SOURCE.splitlines()[1]) if valida else "inválido"
    )
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = respuesta
    esperado = extract_refined_abstracts(SOURCE, llm)
    sink = AbstractRefineDebugSink(tmp_path, "documento")
    with patch(f"pathlib.Path.{fallo}", side_effect=OSError("dato sensible")):
        resultado = extract_refined_abstracts(SOURCE, llm, debug_sink=sink)
    assert resultado.abstracts == esperado.abstracts
    assert resultado.diagnostics() == esperado.diagnostics()
    assert "No se pudo guardar el diagnóstico" in caplog.text
    assert "dato sensible" not in caplog.text


def test_respuesta_existe_antes_de_validar(tmp_path):
    from pdfsum.abstract_refine import parse_refined_abstracts

    cruda = ' {"abstracts": []}\r\n'
    llm = Mock(spec=TextLLM)
    llm.complete_json.return_value = cruda
    sink = AbstractRefineDebugSink(tmp_path, "documento")

    def validar(raw, *args, **kwargs):
        assert (
            tmp_path / "documento/attempt-1-response.txt"
        ).read_bytes() == cruda.encode()
        return parse_refined_abstracts(raw, *args, **kwargs)

    with patch("pdfsum.abstract_refine.parse_refined_abstracts", side_effect=validar):
        extract_refined_abstracts("Sin resumen.", llm, debug_sink=sink)


@pytest.mark.parametrize("intento", [2, 3, 5])
def test_retira_intento_complementario_de_ejecucion_anterior(tmp_path, intento):
    sink = AbstractRefineDebugSink(tmp_path, "documento")
    sink(attempt=intento, raw_response='{"abstracts": []}')
    sink(attempt=intento, metadata={"validation_succeeded": True})
    nuevo = AbstractRefineDebugSink(tmp_path, "documento")
    nuevo(attempt=1, raw_response='{"abstracts": []}')
    assert not list((tmp_path / "documento").glob(f"attempt-{intento}-*"))


@pytest.mark.parametrize("idioma", ["en", "pt"])
@pytest.mark.parametrize("intento", [1, 2])
@pytest.mark.parametrize("invertido", [False, True])
def test_respuesta_mixta_preserva_resultado_con_y_sin_debug(idioma, intento, invertido):
    principal, otro = (_salida("en", "ABSTRACT", _EN), _salida("pt", "RESUMO", _PT))
    if idioma == "pt":
        principal, otro = otro, principal
    valido = json.loads(principal)["abstracts"][0]
    rechazado = json.loads(otro)["abstracts"][0]
    if intento == 1:
        rechazado["text"] = "Contenido inventado sin respaldo en la fuente."
    items = [rechazado, valido] if invertido else [valido, rechazado]
    mixta = json.dumps({"abstracts": items})
    respuestas = [mixta, otro] if intento == 1 else [otro, mixta]
    resultados, diagnosticos, llamadas, eventos = [], [], [], []
    for activo in (False, True):
        llm = Mock(spec=TextLLM)
        llm.complete_json.side_effect = respuestas
        registros, capturas = [], []
        resultado = extract_refined_abstracts(
            _BILINGUE,
            llm,
            event_sink=lambda evento, registros=registros, **campos: registros.append(
                (evento, campos)
            ),
            debug_sink=(lambda capturas=capturas, **campos: capturas.append(campos))
            if activo
            else None,
        )
        resultados.append(resultado.abstracts)
        diagnosticos.append(resultado.diagnostics())
        llamadas.append(llm.complete_json.call_args_list)
        eventos.append(registros)
        assert [a.text for a in resultado.abstracts] == [_EN, _PT]
        assert resultado.diagnostics()["completion_succeeded"]
        assert not resultado.diagnostics()["fallback"]
        if activo:
            datos = next(
                c["metadata"]
                for c in capturas
                if c["attempt"] == intento and "metadata" in c
            )
            assert datos["validation_succeeded"]
            assert len(datos["validation"]) == 2
            assert sum(bool(m["rejection_reason"]) for m in datos["validation"]) == 1
    assert resultados[0] == resultados[1]
    assert diagnosticos[0] == diagnosticos[1]
    assert llamadas[0] == llamadas[1]
    assert eventos[0] == eventos[1]


def test_todos_invalidos_activan_fallback_con_y_sin_debug():
    esperado = extract_refined_abstracts(SOURCE, None).abstracts
    for activo in (False, True):
        capturas = []
        llm = Mock(spec=TextLLM)
        llm.complete_json.return_value = '{"abstracts": [null, {}]}'
        resultado = extract_refined_abstracts(
            SOURCE,
            llm,
            debug_sink=(lambda capturas=capturas, **campos: capturas.append(campos))
            if activo
            else None,
        )
        assert resultado.abstracts == esperado
        assert resultado.diagnostics()["fallback"]
        assert not resultado.diagnostics()["refinement_succeeded"]
        llm.complete_json.assert_called_once()
        if activo:
            datos = capturas[-1]["metadata"]
            assert not datos["validation_succeeded"]
            assert datos["error_type"] == "ValueError"
            assert len(datos["validation"]) == 2


@pytest.mark.parametrize("inicial", ["pt", "en", None])
@pytest.mark.parametrize(
    "fallo", ["ninguno", "otro_idioma", "repetido", "vacio", "inventado"]
)
def test_complemento_dirigido_por_idioma_con_y_sin_debug(inicial, fallo):
    textos = {"pt": _PT, "en": _EN}
    encabezados = {"pt": "RESUMO", "en": "ABSTRACT"}
    pendientes = [idioma for idioma in ("en", "pt") if idioma != inicial]
    primera = (
        _salida(inicial, encabezados[inicial], textos[inicial])
        if inicial
        else '{"abstracts":[]}'
    )
    respuestas = [primera]
    for idioma in pendientes:
        if fallo == "ninguno":
            respuesta = _salida(idioma, encabezados[idioma], textos[idioma])
        elif fallo == "otro_idioma":
            respuesta = _salida("es", "RESUMEN", "Un resumen ajeno.")
        elif fallo == "repetido":
            otro = inicial or ("pt" if idioma == "en" else "en")
            respuesta = _salida(otro, encabezados[otro], textos[otro])
        elif fallo == "vacio":
            respuesta = '{"abstracts":[]}'
        else:
            respuesta = _salida(
                idioma, encabezados[idioma], textos[idioma] + " Inventado."
            )
        respuestas.append(respuesta)
    ejecuciones = []
    for activo in (False, True):
        llm = Mock(spec=TextLLM)
        llm.complete_json.side_effect = respuestas
        capturas, eventos = [], []
        resultado = extract_refined_abstracts(
            _BILINGUE,
            llm,
            debug_sink=(lambda capturas=capturas, **campos: capturas.append(campos))
            if activo
            else None,
            event_sink=lambda evento, eventos=eventos, **campos: eventos.append(
                (evento, campos)
            ),
        )
        esperado = (
            ["en", "pt"] if fallo == "ninguno" else ([inicial] if inicial else [])
        )
        assert [a.lang for a in resultado.abstracts] == esperado
        assert [a.text for a in resultado.abstracts] == [textos[i] for i in esperado]
        assert resultado.diagnostics()["completion_retry_succeeded"] == (
            fallo == "ninguno"
        )
        assert llm.complete_json.call_count == 1 + len(pendientes)
        for intento, idioma in enumerate(pendientes, 2):
            prompt = llm.complete_json.call_args_list[intento - 1].args[0]
            datos = json.loads(prompt.splitlines()[-1])
            assert datos["target_lang"] == idioma
            assert datos["transcription_fragments"] == [textos[idioma]]
            assert all(e["lang"] == idioma for e in datos["missing_abstract_evidence"])
            assert "No resumas, traduzcas, parafrasees ni completes contenido" in prompt
            assert '{"abstracts":[]}' in prompt
            if activo:
                metadata = next(
                    c["metadata"]
                    for c in capturas
                    if c["attempt"] == intento and "metadata" in c
                )
                assert metadata["target_lang"] == idioma
                assert metadata["validation_succeeded"] == (fallo == "ninguno")
                if fallo != "ninguno":
                    assert metadata["rejection_reason"]
        ejecuciones.append((resultado.abstracts, resultado.diagnostics(), eventos))
    assert ejecuciones[0] == ejecuciones[1]
