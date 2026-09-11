"""Flujo externo sin MongoDB, red, OCR real ni LLM remoto."""

import io
import json
import sys
from email.message import Message
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import pytest

from pdfsum.adapters.external_http import HTTPMaterializer, MaterializationError
from pdfsum.adapters.external_processor import LocalInputProcessor
from pdfsum.adapters.external_runner import ResultStoreError, execute_external
from pdfsum.adapters.fake_summarizer import FakeSummarizer
from pdfsum.adapters.fake_transcriber import FakeTranscriber
from pdfsum.cli import main
from pdfsum.external import INPUT_TYPES, ExternalInput
from pdfsum.workspace import Workspace

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
TEXT = "Resumen\nEste documento describe un estudio de salud pública.\n" * 20
SECRET = "https://usuario:clave@servidor/recurso?token=secreto"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Desactiva telemetría remota y bloquea conexiones accidentales en estos tests."""
    monkeypatch.setenv("PDFSUM_OLLAMA_METRICS", "0")

    def reject_connection(*args, **kwargs):
        raise AssertionError("Los tests externos no deben abrir conexiones reales")

    monkeypatch.setattr("socket.create_connection", reject_connection)


class FakeSource:
    """Reserva una sola vez; el store de prueba confirma los resultados."""

    def __init__(self, entries):
        self.entries = entries
        self.claimed = set()

    def pending(self, command):
        for index, entry in enumerate(self.entries):
            key = command, index
            if key not in self.claimed:
                self.claimed.add(key)
                yield entry


class FakeStore:
    """Conserva objetos originales, sin serialización ni conocimiento de MongoDB."""

    def __init__(self):
        self.results = []

    def save(self, result):
        self.results.append(result)


class Response(io.BytesIO):
    """Respuesta HTTP simulada con lecturas acotadas."""

    def __init__(self, content, content_type=None, status=200, length=None):
        super().__init__(content)
        self.status = status
        self.headers = Message()
        if content_type:
            self.headers["Content-Type"] = content_type
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def read(self, size=-1):
        assert 0 < size <= 65536
        return super().read(size)


def downloader(content, content_type=None, **kwargs):
    opener = Mock(side_effect=lambda *a, **k: Response(content, content_type))
    return HTTPMaterializer(opener=opener, **kwargs)


def processor(ws):
    return LocalInputProcessor(
        ws, transcriber=FakeTranscriber(TEXT), summarizer=FakeSummarizer()
    )


@pytest.mark.parametrize("command", INPUT_TYPES)
@pytest.mark.parametrize("keep", [False, True])
def test_four_commands_preserve_id_and_artifacts(tmp_path, command, keep):
    """Ejecuta los pipelines reales con puertos OCR/LLM fake y el mismo ID opaco."""
    identifier = object()
    input_type = INPUT_TYPES[command]
    entry = ExternalInput(
        identifier, input_type, "https://servidor/recurso?token=secreto"
    )
    source, store = FakeSource([entry]), FakeStore()
    ws = Workspace(tmp_path)
    proc = processor(ws)
    materializer = downloader(PDF if input_type == "pdf" else TEXT.encode())
    counts = execute_external(
        command, source, materializer, proc, store, ws, keep_artifacts=keep
    )
    assert counts == {"completed": 1, "failed": 0}
    assert store.results[0].id is identifier
    assert store.results[0].command == command
    downloads = list(ws.downloads_dir.iterdir())
    assert bool(downloads) is keep
    mains = (
        list(ws.abstracts_dir.glob("*.json"))
        if command == "extract-abstracts"
        else [p for p in ws.summaries_dir.glob("*.json") if p.name != "report.json"]
    )
    assert bool(mains) is (keep and command != "transcribe")
    result = store.results[0].result
    if command == "transcribe":
        assert result == TEXT
    elif command == "run":
        assert "_qa" in result and result["meta"]["text_cleaned"]
    elif command == "extract-abstracts":
        assert "abstracts" in result and "source_kind" in result
    else:
        assert "secciones" in result and "_qa" not in result
    if mains:
        assert json.loads(mains[0].read_text()) == result
    if input_type == "pdf":
        assert len(list(ws.ocr_dir.glob("*.txt"))) == 1
    if command in {"run", "extract-abstracts"}:
        assert ws.report_path.exists()
    assert (ws.report_path.parent / "events.jsonl").exists()
    assert execute_external(command, source, materializer, proc, store, ws) == {
        "completed": 0,
        "failed": 0,
    }
    assert len(store.results) == 1


@pytest.mark.parametrize("command", INPUT_TYPES)
def test_incompatible_type_is_saved_without_processing(tmp_path, command):
    kind = "pdf" if command == "summarize" else "text"
    identifier = object()
    store, materializer, proc = FakeStore(), Mock(), Mock()
    execute_external(
        command,
        FakeSource([ExternalInput(identifier, kind, SECRET)]),
        materializer,
        proc,
        store,
        Workspace(tmp_path),
    )
    result = store.results[0]
    assert result.id is identifier and result.phase == "validacion"
    assert result.status == "failed"
    materializer.materialize.assert_not_called()
    proc.process.assert_not_called()


@pytest.mark.parametrize(
    "kind,content,content_type",
    [
        ("pdf", PDF, "application/pdf"),
        ("pdf", PDF, "application/octet-stream"),
        ("text", TEXT.encode(), "text/plain; charset=utf-8"),
        ("text", TEXT.encode("utf-16"), "text/plain; charset=utf-16"),
        ("text", TEXT.encode("utf-8-sig"), None),
        ("text", ("á" * 40000).encode(), "text/plain"),
    ],
)
def test_materializes_streaming(tmp_path, kind, content, content_type):
    path = tmp_path / "recurso"
    materializer = downloader(content, content_type, timeout=7)
    materializer.materialize(
        ExternalInput(7, kind, "https://servidor/sin-extension"), path
    )
    materializer.opener.assert_called_once_with(
        "https://servidor/sin-extension", timeout=7
    )
    if kind == "pdf":
        assert path.read_bytes() == PDF
    else:
        assert path.read_text() == ("á" * 40000 if len(content) > 65536 else TEXT)


@pytest.mark.parametrize(
    "kind,content,content_type",
    [
        ("pdf", b"", "application/pdf"),
        ("text", b"", "text/plain"),
        ("pdf", b"<html>error</html>", "application/pdf"),
        ("pdf", b"%PDF-1.4 truncado", "application/pdf"),
        ("pdf", PDF, "text/html"),
        ("text", b"\xff\xfe\x01", "text/plain"),
        ("text", b"texto\x00binario", "text/plain"),
        ("text", b"   \n", "text/plain"),
        ("text", b"\xff", "text/plain; charset=utf-8"),
        ("text", b"texto", "text/plain; charset=desconocido"),
        ("text", b"texto", "text/plain; charset=latin-1"),
        ("text", PDF, "text/plain"),
        ("text", b"<html>error</html>", "text/html"),
    ],
)
def test_invalid_resource_is_rejected_and_removed(
    tmp_path, kind, content, content_type
):
    path = tmp_path / "recurso"
    with pytest.raises(MaterializationError):
        downloader(content, content_type).materialize(
            ExternalInput(1, kind, "https://servidor/recurso"), path
        )
    assert not path.exists()


@pytest.mark.parametrize("command", INPUT_TYPES)
def test_http_error_preserves_id_and_hides_url(tmp_path, caplog, command):
    identifier = object()
    store = FakeStore()
    opener = Mock(side_effect=HTTPError(SECRET, 403, SECRET, {}, None))
    execute_external(
        command,
        FakeSource(
            [
                ExternalInput(
                    identifier, INPUT_TYPES[command], "https://servidor/?token=secreto"
                )
            ]
        ),
        HTTPMaterializer(opener=opener),
        processor(Workspace(tmp_path)),
        store,
        Workspace(tmp_path),
    )
    result = store.results[0]
    assert result.id is identifier and result.status == "failed"
    assert result.phase == "materializacion"
    assert not list((tmp_path / "downloads").iterdir())
    logs = caplog.text + (tmp_path / "summaries/events.jsonl").read_text()
    assert "secreto" not in logs and "clave" not in logs and "usuario" not in logs


@pytest.mark.parametrize("kind", ["pdf", "text"])
def test_processor_failure_cleans_only_owned_files(tmp_path, kind):
    command = "run" if kind == "pdf" else "summarize"
    identifier, ws, store = object(), Workspace(tmp_path), FakeStore()
    ws.ocr_dir.mkdir()
    ws.ocr_path("previo").write_text("OCR")
    ws.summaries_dir.mkdir()
    ws.summary_path("previo").write_text("resultado previo")
    (ws.summaries_dir / "events.jsonl").write_text("")
    proc = processor(ws)

    def fail(command, path):
        ws.summary_path(path.stem).write_text("parcial")
        raise RuntimeError(SECRET)

    proc.process = fail
    execute_external(
        command,
        FakeSource([ExternalInput(identifier, kind, "https://s/r")]),
        downloader(PDF if kind == "pdf" else TEXT.encode()),
        proc,
        store,
        ws,
    )
    assert store.results[0].id is identifier
    assert store.results[0].phase == "procesamiento"
    assert ws.ocr_path("previo").read_text() == "OCR"
    assert ws.summary_path("previo").read_text() == "resultado previo"
    assert list(ws.summaries_dir.glob("*.json")) == [ws.summary_path("previo")]
    assert not list(ws.downloads_dir.iterdir())
    assert SECRET not in (ws.summaries_dir / "events.jsonl").read_text()


def test_store_error_retains_envelope_and_stops(tmp_path):
    identifier = object()
    source = FakeSource(
        [
            ExternalInput(identifier, "text", "https://s/r"),
            ExternalInput("siguiente", "text", "https://s/r"),
        ]
    )
    ws = Workspace(tmp_path)
    store = Mock()
    store.save.side_effect = RuntimeError(SECRET)
    with pytest.raises(ResultStoreError) as caught:
        execute_external(
            "summarize", source, downloader(TEXT.encode()), processor(ws), store, ws
        )
    assert caught.value.id is identifier
    assert caught.value.result.result["secciones"]
    assert caught.value.phase == "persistencia"
    assert SECRET not in str(caught.value)
    assert len(source.claimed) == 1
    assert not list(ws.downloads_dir.iterdir())
    assert not list(ws.summaries_dir.glob("*.json"))
    assert "external_store_failed" in (ws.summaries_dir / "events.jsonl").read_text()


@pytest.mark.parametrize(
    "identifier", ["../../fuera", "/etc/passwd", "a\\b", "x%2f..", 123]
)
def test_local_names_are_safe(tmp_path, identifier):
    ws, store = Workspace(tmp_path), FakeStore()
    execute_external(
        "summarize",
        FakeSource([ExternalInput(identifier, "text", "https://s")]),
        downloader(TEXT.encode()),
        processor(ws),
        store,
        ws,
        keep_artifacts=True,
    )
    assert store.results[0].id is identifier
    (downloaded,) = ws.downloads_dir.iterdir()
    assert downloaded.parent == ws.downloads_dir
    assert len(downloaded.stem) == 53


def test_download_limits_and_partial_response(tmp_path):
    entry = ExternalInput(1, "pdf", "https://s")
    with pytest.raises(MaterializationError):
        downloader(PDF, max_bytes=5).materialize(entry, tmp_path / "limitado")
    with pytest.raises(MaterializationError):
        HTTPMaterializer(opener=lambda *a, **k: Response(PDF, length=999)).materialize(
            entry, tmp_path / "incompleto"
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://servidor/r", SECRET])
def test_unsafe_url_is_not_opened(tmp_path, url):
    opener = Mock()
    with pytest.raises(MaterializationError):
        HTTPMaterializer(opener=opener).materialize(
            ExternalInput(1, "pdf", url), tmp_path / "recurso"
        )
    opener.assert_not_called()


@pytest.mark.parametrize("command", INPUT_TYPES)
def test_external_cli_with_non_mongo_provider(tmp_path, command):
    store, identifier = FakeStore(), object()
    module = ModuleType("proveedor_prueba")
    module.create = lambda config: (
        FakeSource(
            [
                ExternalInput(
                    identifier, INPUT_TYPES[command], "https://servidor/recurso"
                )
            ]
        ),
        store,
    )
    content = PDF if INPUT_TYPES[command] == "pdf" else TEXT.encode()
    with (
        patch.dict(sys.modules, {"proveedor_prueba": module}),
        patch(
            "pdfsum.adapters.external_http.HTTPMaterializer",
            return_value=downloader(content),
        ),
    ):
        assert (
            main(
                [
                    "external",
                    command,
                    "--provider",
                    "proveedor_prueba:create",
                    "--workspace",
                    str(tmp_path),
                    "--fake",
                    "--keep-artifacts",
                ]
            )
            == 0
        )
    assert store.results[0].id is identifier
    assert list((tmp_path / "downloads").iterdir())


def test_missing_mongodb_dependency_is_clear(tmp_path, capsys):
    with patch("pdfsum.adapters.external_mongodb.find_spec", return_value=None):
        assert (
            main(
                [
                    "external",
                    "run",
                    "--provider",
                    "mongodb",
                    "--workspace",
                    str(tmp_path),
                    "--fake",
                ]
            )
            == 2
        )
    assert "dependencia opcional pymongo" in capsys.readouterr().out


def test_mongodb_does_not_assume_schema(tmp_path, capsys):
    with (
        patch("pdfsum.adapters.external_mongodb.find_spec", return_value=object()),
        patch.dict(
            "os.environ",
            {"PDFSUM_MONGODB_URI": "mongodb://usuario:clave@servidor/base"},
        ),
    ):
        assert (
            main(
                [
                    "external",
                    "run",
                    "--provider",
                    "mongodb",
                    "--workspace",
                    str(tmp_path),
                    "--fake",
                ]
            )
            == 2
        )
    output = capsys.readouterr().out
    assert "pendiente de schema" in output
    assert "clave" not in output


def test_generic_modules_do_not_import_pymongo():
    import ast

    root = Path(__file__).parents[1] / "src/pdfsum"
    for file in [root / "external.py", *root.glob("adapters/external_*.py")]:
        imports = [
            node
            for node in ast.walk(ast.parse(file.read_text()))
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert all("pymongo" not in ast.unparse(node) for node in imports)


@pytest.mark.parametrize("url", ["ftp://servidor/r", "file:///etc/passwd", SECRET])
def test_redirects_reject_unsafe_targets(url):
    from urllib.request import Request

    from pdfsum.adapters.external_http import _HTTPRedirect

    with pytest.raises(ValueError, match="URL HTTP inválida"):
        _HTTPRedirect().redirect_request(
            Request("https://servidor"), None, 302, "redirección", {}, url
        )


def test_cleanup_failure_preserves_id_and_attempts_other_files(tmp_path):
    from pdfsum.adapters.external_runner import ArtifactCleanupError

    ws, store, identifier = Workspace(tmp_path), FakeStore(), object()
    original = Path.unlink

    def cannot_remove_download(path, *args, **kwargs):
        if path.parent == ws.downloads_dir:
            raise PermissionError("archivo ocupado")
        return original(path, *args, **kwargs)

    with (
        patch.object(Path, "unlink", cannot_remove_download),
        pytest.raises(ArtifactCleanupError) as caught,
    ):
        execute_external(
            "summarize",
            FakeSource([ExternalInput(identifier, "text", "https://servidor")]),
            downloader(TEXT.encode()),
            processor(ws),
            store,
            ws,
        )
    assert caught.value.id is identifier
    assert store.results[0].id is identifier
    assert not list(ws.summaries_dir.glob("*.json"))
    assert "external_cleanup_failed" in (ws.summaries_dir / "events.jsonl").read_text()


@pytest.mark.parametrize("command", ["run", "extract-abstracts"])
def test_real_runner_sanitizes_provider_errors(tmp_path, caplog, command):
    ws, store = Workspace(tmp_path), FakeStore()
    llm = Mock()
    llm.provider = "prueba"
    llm.model = "modelo"
    llm.summarize.side_effect = RuntimeError(SECRET + TEXT)
    llm.complete_json.side_effect = RuntimeError(SECRET + TEXT)
    proc = LocalInputProcessor(ws, transcriber=FakeTranscriber(TEXT), summarizer=llm)
    execute_external(
        command,
        FakeSource([ExternalInput(1, "pdf", "https://s")]),
        downloader(PDF),
        proc,
        store,
        ws,
    )
    logs = caplog.text + (ws.summaries_dir / "events.jsonl").read_text()
    logs += ws.report_path.read_text()
    assert "secreto" not in logs and "clave" not in logs
    assert TEXT not in logs
    # La revisión fallida conserva el fallback determinista habitual.
    assert store.results[0].status == ("failed" if command == "run" else "completed")
