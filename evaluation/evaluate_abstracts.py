"""Evaluador experimental de abstracts, independiente del flujo de producción."""

import argparse
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path

DEFAULT_THRESHOLDS = (0.80, 0.85, 0.90, 0.92, 0.95, 0.97, 0.98, 0.99)


class EvaluationError(ValueError):
    """Indica datos de evaluación inválidos."""


def normalize_text(text: str) -> str:
    """Normaliza a NFC y minúsculas; conserva los acentos y la puntuación."""
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def similarity(reference: str, prediction: str) -> float:
    """Calcula Levenshtein normalizada sobre textos ya normalizados."""
    if reference == prediction:
        return 1.0
    if not reference or not prediction:
        return 0.0
    if len(reference) < len(prediction):
        reference, prediction = prediction, reference
    previous = list(range(len(prediction) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(prediction, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return 1.0 - previous[-1] / len(reference)


def validate_document(value: object, location: str) -> dict:
    """Comprueba los campos necesarios sin depender del modelo de producción."""
    if not isinstance(value, dict):
        raise EvaluationError(f"{location}: se esperaba un objeto JSON")
    if not isinstance(value.get("doc_id"), str) or not value["doc_id"].strip():
        raise EvaluationError(f"{location}: falta doc_id o no es una cadena válida")
    if not isinstance(value.get("abstracts"), list):
        raise EvaluationError(f"{location}: abstracts debe ser una lista")
    for index, abstract in enumerate(value["abstracts"]):
        if (
            not isinstance(abstract, dict)
            or not isinstance(abstract.get("lang"), str)
            or not abstract["lang"].strip()
            or not isinstance(abstract.get("text"), str)
        ):
            raise EvaluationError(
                f"{location}: abstract {index} requiere lang no vacío y text de tipo cadena"
            )
    return value


def load_documents(reference: Path, predictions: Path) -> tuple[dict, dict]:
    """Lee el gold standard y los JSON individuales; nunca usa report.json."""
    if not predictions.is_dir():
        raise EvaluationError(f"No existe el directorio de predictions: {predictions}")
    expected, predicted = {}, {}
    with reference.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            location = f"{reference}, línea {number}"
            try:
                document = validate_document(json.loads(line), location)
            except json.JSONDecodeError as exc:
                raise EvaluationError(
                    f"{location}: JSON inválido, columna {exc.colno}"
                ) from exc
            if document["doc_id"] in expected:
                raise EvaluationError(
                    f"{location}: doc_id duplicado: {document['doc_id']}"
                )
            expected[document["doc_id"]] = document
    for path in sorted(predictions.glob("*.json")):
        if path.name == "report.json":
            continue
        try:
            document = validate_document(
                json.loads(path.read_text(encoding="utf-8")), str(path)
            )
        except json.JSONDecodeError as exc:
            raise EvaluationError(
                f"{path}: JSON de predicción inválido, columna {exc.colno}"
            ) from exc
        if document["doc_id"] in predicted:
            raise EvaluationError(f"{path}: doc_id duplicado: {document['doc_id']}")
        predicted[document["doc_id"]] = document
    return expected, predicted


def similarity_stats(values: list[float]) -> dict:
    """Resume los pares; los percentiles usan interpolación lineal."""
    ordered = sorted(values)

    def percentile(fraction):
        position = (len(ordered) - 1) * fraction
        lower = math.floor(position)
        upper = math.ceil(position)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    result = dict.fromkeys(("mean", "median", "min", "max", "p10", "p25", "p75", "p90"))
    if values:
        result.update(
            mean=statistics.mean(values),
            median=statistics.median(values),
            min=ordered[0],
            max=ordered[-1],
            **{f"p{p}": percentile(p / 100) for p in (10, 25, 75, 90)},
        )
    return {"count": len(values), **result}


def evaluate(reference: Path, predictions: Path, thresholds=DEFAULT_THRESHOLDS) -> dict:
    """Evalúa cada abstract y cuenta TEXT_MISMATCH como un FP y un FN."""
    thresholds = tuple(dict.fromkeys(float(value) for value in thresholds))
    if not thresholds or any(
        not math.isfinite(t) or not 0 <= t <= 1 for t in thresholds
    ):
        raise EvaluationError("Los thresholds deben ser números finitos entre 0 y 1")
    expected, predicted = load_documents(reference, predictions)
    totals = {
        str(t): dict.fromkeys(("tp", "fp", "fn", "tn", "text_mismatch"), 0)
        for t in thresholds
    }
    documents, scores = [], []
    for doc_id in sorted(expected.keys() | predicted.keys()):
        gold = expected.get(doc_id, {}).get("abstracts", [])
        prediction = predicted.get(doc_id, {})
        abstracts = prediction.get("abstracts", [])
        normalized = [normalize_text(a["text"]) for a in abstracts]
        unused = set(range(len(abstracts)))
        matches = []
        for index, abstract in enumerate(gold):
            text = normalize_text(abstract["text"])
            candidates = [
                i for i in sorted(unused) if abstracts[i]["lang"] == abstract["lang"]
            ]
            best, score = None, None
            if candidates:
                score, best = max(
                    ((similarity(text, normalized[i]), i) for i in candidates),
                    key=lambda pair: (pair[0], -pair[1]),
                )
                unused.remove(best)
                scores.append(score)
            classifications = {}
            for threshold in thresholds:
                counts = totals[str(threshold)]
                if best is None:
                    classification = "FN"
                    counts["fn"] += 1
                elif score >= threshold:
                    classification = "TP"
                    counts["tp"] += 1
                else:
                    classification = "TEXT_MISMATCH"
                    counts["text_mismatch"] += 1
                    counts["fp"] += 1
                    counts["fn"] += 1
                classifications[str(threshold)] = classification
            matches.append(
                {
                    "expected_index": index,
                    "predicted_index": best,
                    "lang": abstract["lang"],
                    "similarity": score,
                    "classifications": classifications,
                    "reference_excerpt": text[:200],
                    "prediction_excerpt": normalized[best][:200]
                    if best is not None
                    else None,
                }
            )
        tn = doc_id in expected and doc_id in predicted and not gold and not abstracts
        for counts in totals.values():
            counts["fp"] += len(unused)
            counts["tn"] += int(tn)
        document = {
            "doc_id": doc_id,
            "reference_present": doc_id in expected,
            "prediction_present": doc_id in predicted,
            "expected_abstract_count": len(gold),
            "predicted_abstract_count": len(abstracts),
            "document_classification": "TN" if tn else None,
            "matched_abstracts": matches,
            "extra_predictions": [
                {
                    "predicted_index": i,
                    "lang": abstracts[i]["lang"],
                    "classification": "FP",
                    "prediction_excerpt": normalized[i][:200],
                }
                for i in sorted(unused)
            ],
        }
        if "source_kind" in prediction:
            document["source_kind"] = prediction["source_kind"]
        documents.append(document)
    for counts in totals.values():
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        counts["precision"] = tp / (tp + fp) if tp + fp else 0.0
        counts["recall"] = tp / (tp + fn) if tp + fn else 0.0
        counts["f1"] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    return {
        "reference": str(reference),
        "predictions": str(predictions),
        "documents": documents,
        "similarity_stats": similarity_stats(scores),
        "thresholds": totals,
    }


class EvaluationParser(argparse.ArgumentParser):
    """Presenta la ayuda y los errores de argumentos en español."""

    def format_usage(self):
        return super().format_usage().replace("usage:", "Uso:", 1)

    def format_help(self):
        return super().format_help().replace("usage:", "Uso:", 1)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Error: argumentos inválidos o incompletos; consulte --help.\n")


def main(argv=None) -> int:
    """Ejecuta la evaluación y guarda el informe JSON."""
    parser = EvaluationParser(description=__doc__, add_help=False)
    parser._positionals.title = "Argumentos posicionales"
    parser._optionals.title = "Opciones"
    parser.add_argument(
        "-h", "--help", action="help", help="Muestra esta ayuda y termina"
    )
    parser.add_argument(
        "--reference", required=True, type=Path, help="Archivo JSONL del gold standard"
    )
    parser.add_argument(
        "--predictions",
        required=True,
        type=Path,
        help="Directorio de JSON individuales",
    )
    parser.add_argument(
        "--out", required=True, type=Path, help="Archivo JSON del informe"
    )
    parser.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=DEFAULT_THRESHOLDS,
        help="Thresholds separados por espacios, entre 0 y 1",
    )
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.reference, args.predictions, args.thresholds)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(
            f"Error de evaluación: no se pudo leer o escribir el archivo "
            f"{exc.filename} (código {exc.errno})",
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(f"Error de evaluación: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
