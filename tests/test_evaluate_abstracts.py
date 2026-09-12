"""Tests del evaluador offline de abstracts."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.evaluate_abstracts import (
    evaluate,
    normalize_text,
    similarity,
    similarity_stats,
)


def abstract(text="Resumen de salud.", lang="es"):
    return {"lang": lang, "text": text}


def document(doc_id="uno", abstracts=None):
    return {"doc_id": doc_id, "abstracts": abstracts or []}


def inputs(tmp_path, gold, predictions):
    reference = tmp_path / "reference.jsonl"
    reference.write_text("".join(json.dumps(d) + "\n" for d in gold), encoding="utf-8")
    directory = tmp_path / "abstracts"
    directory.mkdir()
    for index, prediction in enumerate(predictions):
        (directory / f"{index}.json").write_text(
            json.dumps(prediction), encoding="utf-8"
        )
    return reference, directory


def test_normalizacion():
    assert normalize_text("  SALUD\r\n Pública.\t ¡SÍ!  ") == "salud pública. ¡sí!"
    assert normalize_text("á.") != normalize_text("a")


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("salud", "salud", 1),
        ("casas", "casa", 0.8),
        ("casa", "cosa", 0.75),
        ("", "", 1),
        ("", "salud", 0),
        ("salud", "", 0),
        ("ab", "ba", 0),
    ],
)
def test_levenshtein(left, right, expected):
    assert similarity(left, right) == pytest.approx(expected)
    assert similarity(right, left) == pytest.approx(expected)


@pytest.mark.parametrize(
    "gold,predicted,classification,counts",
    [
        ([abstract()], [abstract()], "TP", (1, 0, 0, 0, 0)),
        ([abstract()], [], "FN", (0, 0, 1, 0, 0)),
        ([], [abstract()], "FP", (0, 1, 0, 0, 0)),
        ([], [], "TN", (0, 0, 0, 1, 0)),
        ([abstract("aaaa")], [abstract("bbbb")], "TEXT_MISMATCH", (0, 1, 1, 0, 1)),
    ],
)
def test_clasificaciones(tmp_path, gold, predicted, classification, counts):
    report = evaluate(
        *inputs(tmp_path, [document(abstracts=gold)], [document(abstracts=predicted)])
    )
    metrics = report["thresholds"]["0.95"]
    assert (
        tuple(metrics[k] for k in ("tp", "fp", "fn", "tn", "text_mismatch")) == counts
    )
    detail = report["documents"][0]
    if gold:
        assert (
            detail["matched_abstracts"][0]["classifications"]["0.95"] == classification
        )
    elif predicted:
        assert detail["extra_predictions"][0]["classification"] == classification
    else:
        assert detail["document_classification"] == classification


def test_idiomas_y_no_reutilizacion(tmp_path):
    gold = [abstract("uno", "pt"), abstract("dos", "es"), abstract("uno", "pt")]
    prediction = [abstract("dos", "es"), abstract("uno", "pt"), abstract("uno", "en")]
    report = evaluate(
        *inputs(tmp_path, [document(abstracts=gold)], [document(abstracts=prediction)])
    )
    matches = report["documents"][0]["matched_abstracts"]
    assert [m["predicted_index"] for m in matches] == [1, 0, None]
    assert report["thresholds"]["0.95"]["fp"] == 1


def test_mejor_candidato_y_empate(tmp_path):
    report = evaluate(
        *inputs(
            tmp_path,
            [document(abstracts=[abstract("salud")])],
            [
                document(
                    abstracts=[abstract("salu"), abstract("salud"), abstract("salud")]
                )
            ],
        )
    )
    assert report["documents"][0]["matched_abstracts"][0]["predicted_index"] == 1
    assert report["thresholds"]["0.95"]["fp"] == 2


def test_ausentes_y_extras(tmp_path):
    report = evaluate(
        *inputs(
            tmp_path,
            [document("ausente", [abstract()]), document("vacío")],
            [document("extra", [abstract()]), document("extra_vacío")],
        )
    )
    metrics = report["thresholds"]["0.95"]
    assert (metrics["fp"], metrics["fn"], metrics["tn"]) == (1, 1, 0)
    assert len(report["documents"]) == 4
    assert all(
        not d["reference_present"] or not d["prediction_present"]
        for d in report["documents"]
    )


def test_thresholds_y_metricas(tmp_path):
    report = evaluate(
        *inputs(
            tmp_path,
            [document(abstracts=[abstract("casas"), abstract("salud")])],
            [document(abstracts=[abstract("casa"), abstract("salud")])],
        ),
        thresholds=[0.8, 0.9],
    )
    assert report["thresholds"]["0.8"]["tp"] == 2
    counts = report["thresholds"]["0.9"]
    assert counts["text_mismatch"] == counts["fp"] == counts["fn"] == 1
    assert counts["precision"] == counts["recall"] == counts["f1"] == 0.5


def test_estadisticas():
    assert similarity_stats([]) == {
        "count": 0,
        **dict.fromkeys(["mean", "median", "min", "max", "p10", "p25", "p75", "p90"]),
    }
    stats = similarity_stats([0, 1])
    assert stats == {
        "count": 2,
        "mean": 0.5,
        "median": 0.5,
        "min": 0,
        "max": 1,
        "p10": 0.1,
        "p25": 0.25,
        "p75": 0.75,
        "p90": 0.9,
    }
    assert similarity_stats([0.8])["p90"] == 0.8


@pytest.mark.parametrize(
    "content,message",
    [
        ("{\n", "línea 1: JSON inválido"),
        ('{"abstracts": []}\n', "falta doc_id"),
        ('{"doc_id":"uno"}\n', "abstracts debe ser"),
        ('{"doc_id":"uno","abstracts":[{}]}\n', "requiere lang"),
        ('{"doc_id":"uno","abstracts":[]}\n' * 2, "doc_id duplicado"),
    ],
)
def test_gold_invalido(tmp_path, content, message):
    reference, predictions = inputs(tmp_path, [], [])
    reference.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        evaluate(reference, predictions)


@pytest.mark.parametrize(
    "content,message",
    [("{", "JSON de predicción inválido"), ('{"abstracts":[]}', "falta doc_id")],
)
def test_prediccion_invalida(tmp_path, content, message):
    reference, predictions = inputs(tmp_path, [], [])
    (predictions / "uno.json").write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        evaluate(reference, predictions)


def test_prediccion_duplicada(tmp_path):
    with pytest.raises(ValueError, match="doc_id duplicado"):
        evaluate(*inputs(tmp_path, [], [document(), document()]))


def test_directorio_ausente(tmp_path):
    with pytest.raises(ValueError, match="No existe el directorio"):
        evaluate(tmp_path / "reference.jsonl", tmp_path / "ausente")


@pytest.mark.parametrize(
    "thresholds", [[], [-0.1], [1.1], [float("nan")], [float("inf")]]
)
def test_thresholds_invalidos(tmp_path, thresholds):
    with pytest.raises(ValueError, match="thresholds"):
        evaluate(*inputs(tmp_path, [], []), thresholds=thresholds)


def test_cli_y_report_ignorado(tmp_path):
    reference, predictions = inputs(
        tmp_path, [document()], [{**document(), "source_kind": "nativo"}]
    )
    (predictions / "report.json").write_text("ignorar", encoding="utf-8")
    output = tmp_path / "results" / "evaluation.json"
    script = (
        Path(__file__).resolve().parents[1] / "evaluation" / "evaluate_abstracts.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--reference",
            str(reference),
            "--predictions",
            str(predictions),
            "--out",
            str(output),
            "--thresholds",
            "0.8",
            "0.95",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["documents"][0]["source_kind"] == "nativo"
    assert set(report["thresholds"]) == {"0.8", "0.95"}
    reference.write_text("{", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--reference",
            str(reference),
            "--predictions",
            str(predictions),
            "--out",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Error de evaluación" in result.stderr
