"""MongoDB simulado: sin servidor, DNS, HTTP, OCR ni LLM reales."""

import copy
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from pdfsum.adapters.external_http import HTTPMaterializer
from pdfsum.adapters.external_mongodb import (
    MongoInfrastructureError,
    MongoJobs,
    MongoSelectionError,
    _select_pdf,
    _selected_ids,
    build_mongodb_provider,
)
from pdfsum.adapters.external_runner import ResultStoreError, execute_external
from pdfsum.cli import build_parser
from pdfsum.cli import main as cli_main
from pdfsum.external import ExternalResult
from pdfsum.workspace import Workspace

SECRET = "mongodb://usuario:clave@interno/?token=secreto"
URL = "https://publico.example/archivo.pdf?token=secreto"


def main(arguments):
    return cli_main([str(argument) for argument in arguments])


class DuplicateKeyError(Exception):
    """Simula únicamente la colisión del índice único."""


class Jobs:
    """Colección en memoria con filtros y actualizaciones atómicas bajo lock."""

    def __init__(self):
        self.documents = {}
        self.operations = []
        self.lock = Lock()

    def create_index(self, keys, **options):
        self.operations.append(("indice", keys, options))

    @staticmethod
    def matches(document, query):
        return all(
            document.get(key) in value["$in"]
            if isinstance(value, dict)
            else document.get(key) == value
            for key, value in query.items()
        )

    @staticmethod
    def apply(document, update, inserted=False):
        if inserted:
            document.update(copy.deepcopy(update.get("$setOnInsert", {})))
        document.update(copy.deepcopy(update.get("$set", {})))
        for key, value in update.get("$inc", {}).items():
            document[key] = document.get(key, 0) + value
        for key in update.get("$unset", {}):
            document.pop(key, None)

    def find_one(self, query):
        with self.lock:
            document = self.documents.get((query["id"], query["command"]))
            return (
                copy.deepcopy(document)
                if document is not None and self.matches(document, query)
                else None
            )

    def update_one(self, query, update, upsert=False):
        with self.lock:
            self.operations.append(
                ("actualizar", copy.deepcopy(query), copy.deepcopy(update), upsert)
            )
            key = (query["id"], query["command"])
            document = self.documents.get(key)
            if document is not None and self.matches(document, query):
                self.apply(document, update)
                return SimpleNamespace(matched_count=1)
            if upsert:
                if document is not None:
                    raise DuplicateKeyError()
                document = copy.deepcopy(query)
                self.apply(document, update, inserted=True)
                self.documents[key] = document
            return SimpleNamespace(matched_count=0)

    def find_one_and_update(self, query, update, *, return_document):
        with self.lock:
            self.operations.append(
                (
                    "reclamar",
                    copy.deepcopy(query),
                    copy.deepcopy(update),
                    return_document,
                )
            )
            document = self.documents.get((query["id"], query["command"]))
            if document is None or not self.matches(document, query):
                return None
            self.apply(document, update)
            return copy.deepcopy(document)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Red real prohibida en estos tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setenv("PDFSUM_OLLAMA_METRICS", "0")


def document(identifier=79665, *urls):
    return {
        "_id": "identidad_interna_distinta",
        "id": identifier,
        "electronic_address": [{"_u": url} for url in (urls or (URL,))],
    }


def adapter(documents=None, ids=None, jobs=None):
    documents = documents if documents is not None else [document()]
    source = Mock(spec=["find_one"])
    source.find_one.side_effect = lambda query, projection: next(
        (copy.deepcopy(doc) for doc in documents if doc["id"] == query["id"]), None
    )
    return MongoJobs(
        source, jobs or Jobs(), ids or [79665], duplicate_key_error=DuplicateKeyError
    )


@pytest.mark.parametrize(
    "urls, expected",
    [
        (["http://ejemplo/a.pdf", "https://ejemplo/b.pdf"], "https://ejemplo/b.pdf"),
        (["https://doi.org/10.1000/123", "https://ejemplo/a.html", URL], URL),
        ([URL, "https://ejemplo/otro.pdf"], URL),
        (["http://ejemplo/a.pdf", "http://ejemplo/b.pdf"], "http://ejemplo/a.pdf"),
        (["https://ejemplo/a.PDF?token=valor"], "https://ejemplo/a.PDF?token=valor"),
    ],
)
def test_pdf_selection_preserves_order_and_prefers_https(urls, expected):
    assert _select_pdf(document(79665, *urls)) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://doi.org/10.1000/123",
        "https://ejemplo/pagina.html",
        "https://ejemplo/a.pdf.",
        "https://ejemplo/a.pd",
        "https://ejemplo/a.epub",
        "https://ejemplo/a.jpg",
        "https://youtube.com/watch?v=123",
        "ejemplo/a.pdf",
        "//ejemplo/a.pdf",
        "ftp://ejemplo/a.pdf",
        "file:///a.pdf",
        "https:///a.pdf",
        "https://ejemplo/a.pdf/",
        "https://ejemplo/?archivo=a.pdf",
        " https://ejemplo/a.pdf",
        "https://ejemplo/a\n.pdf",
        "https://usuario:clave@ejemplo/a.pdf",
        "https://ejemplo:incorrecto/a.pdf",
        "https://ejemplo:0/a.pdf",
        "https://ejemplo/a%ZZ.pdf",
        "https://ejemplo\\a.pdf",
        None,
        42,
    ],
)
def test_invalid_resources_are_not_repaired(url):
    with pytest.raises(MongoSelectionError, match="URL PDF utilizable"):
        _select_pdf({"electronic_address": [{"_u": url}]})


def test_queries_functional_id_and_never_mutates_source():
    original = document()
    before = copy.deepcopy(original)
    source = adapter([original])
    entries = list(source.pending("run"))
    assert entries[0].id == 79665
    source.source.find_one.assert_called_once_with(
        {"id": 79665}, {"id": 1, "electronic_address": 1}
    )
    assert original == before
    assert source.jobs.operations[0] == (
        "indice",
        [("id", 1), ("command", 1)],
        {"unique": True, "name": "id_command_unico"},
    )


@pytest.mark.parametrize(
    "command,payload",
    [
        ("run", {"resumen": "resultado", "_qa": {"aprobado": True}}),
        ("extract-abstracts", {"abstracts": [{"texto": "resumen"}]}),
        ("transcribe", "Texto transcrito"),
    ],
)
def test_pending_processing_completed_and_result_only(command, payload):
    source = adapter()
    entry = next(source.pending(command))
    job = source.jobs.documents[(entry.id, command)]
    assert job["status"] == "processing"
    assert source.jobs.operations[1][2]["$setOnInsert"]["status"] == "pending"
    assert job["attempts"] == 1
    source.save(ExternalResult(entry.id, command, "completed", result=payload))
    assert job["status"] == "completed"
    assert job["result"] == payload
    assert "error" not in job
    assert job["created_at"] <= job["started_at"] <= job["finished_at"]
    assert job["finished_at"].tzinfo is not None
    assert not {"ocr", "logs", "report.json", "events.jsonl"} & job.keys()
    assert list(adapter(jobs=source.jobs).pending(command)) == []


@pytest.mark.parametrize(
    "documents,code",
    [
        ([], "id_inexistente"),
        ([{"id": 79665}], "sin_recurso"),
        ([{"id": 79665, "electronic_address": []}], "sin_recurso"),
        (
            [
                {
                    "id": 79665,
                    "electronic_address": [{"_u": "https://ejemplo/pagina.html"}],
                }
            ],
            "sin_pdf",
        ),
    ],
)
def test_selection_failures_are_persisted_and_next_id_continues(documents, code):
    source = adapter([*documents, document(79662)], ids=[79665, 79662])
    entries = list(source.pending("transcribe"))
    assert [entry.id for entry in entries] == [79662]
    failed = source.jobs.documents[(79665, "transcribe")]
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == code
    assert failed["error"]["phase"] == "seleccion"
    assert source.selection_failures == 1


def test_failed_retries_with_new_token_and_old_attempt_cannot_save():
    source = adapter()
    list(source.pending("run"))
    source.save(
        ExternalResult(79665, "run", "failed", phase="materializacion", error=SECRET)
    )
    job = source.jobs.documents[(79665, "run")]
    old_token = job["claim_token"]
    second = adapter(jobs=source.jobs)
    assert len(list(second.pending("run"))) == 1
    assert job["attempts"] == 2 and job["claim_token"] != old_token
    assert "error" not in job and "finished_at" not in job
    with pytest.raises(MongoInfrastructureError):
        source.save(ExternalResult(79665, "run", "completed", result={}))
    result = ExternalResult(79665, "run", "completed", result={"texto": "bien"})
    second.save(result)
    finished = job["finished_at"]
    second.save(result)
    assert job["finished_at"] == finished
    assert job["status"] == "completed"


def test_atomic_claim_allows_only_one_worker():
    jobs = Jobs()
    workers = [adapter(jobs=jobs), adapter(jobs=jobs)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda worker: list(worker.pending("run")), workers))
    assert sum(map(len, results)) == 1
    claims = [operation for operation in jobs.operations if operation[0] == "reclamar"]
    assert len(claims) == 2
    for _, query, update, after in claims:
        assert query == {
            "id": 79665,
            "command": "run",
            "status": {"$in": ["pending", "failed"]},
        }
        assert update["$set"]["status"] == "processing"
        assert after is True
    assert len(jobs.documents) == 1


def test_different_commands_have_separate_jobs():
    source = adapter()
    assert len(list(source.pending("run"))) == 1
    assert len(list(source.pending("transcribe"))) == 1
    assert len(source.jobs.documents) == 2


def test_insert_race_still_uses_atomic_claim(monkeypatch):
    source = adapter()
    source.jobs.documents[(79665, "run")] = {
        "id": 79665,
        "command": "run",
        "status": "pending",
    }
    monkeypatch.setattr(
        source.jobs, "update_one", Mock(side_effect=DuplicateKeyError(SECRET))
    )
    assert len(list(source.pending("run"))) == 1


def test_store_sanitizes_untrusted_failure_fields():
    source = adapter()
    list(source.pending("run"))
    source.save(
        ExternalResult(
            79665, "run", "failed", phase=SECRET, error_type=SECRET, error=SECRET
        )
    )
    assert SECRET not in repr(source.jobs.documents)
    assert source.jobs.documents[(79665, "run")]["error"] == {
        "phase": "procesamiento",
        "code": "entrada_fallida",
        "message": "Falló la entrada; detalle omitido por privacidad",
    }


@pytest.mark.parametrize(
    "operation", ["create_index", "update_one", "find_one_and_update", "find_one"]
)
def test_database_errors_are_infrastructure_and_sanitized(
    operation, monkeypatch, caplog
):
    source = adapter()
    target = source.source if operation == "find_one" else source.jobs
    monkeypatch.setattr(target, operation, Mock(side_effect=RuntimeError(SECRET)))
    with pytest.raises(MongoInfrastructureError) as caught:
        list(source.pending("run"))
    assert SECRET not in str(caught.value) + caplog.text


def test_persist_failure_stops_executor(tmp_path, monkeypatch):
    source = adapter([document(), document(79662)], ids=[79665, 79662])
    original = source.jobs.update_one

    def fail_save(query, update, **kwargs):
        if "claim_token" in query:
            raise RuntimeError(SECRET)
        return original(query, update, **kwargs)

    monkeypatch.setattr(source.jobs, "update_one", fail_save)
    processor = Mock()
    processor.temporary_results.return_value = []
    processor.process.return_value = {"resumen": "bien"}
    with pytest.raises(ResultStoreError) as caught:
        execute_external("run", source, Mock(), processor, source, Workspace(tmp_path))
    assert caught.value.id == 79665
    assert SECRET not in str(caught.value)
    assert (79662, "run") not in source.jobs.documents


@pytest.mark.parametrize("phase", ["materializacion", "procesamiento"])
def test_entry_errors_fail_only_one_job(tmp_path, phase):
    source = adapter([document(), document(79662)], ids=[79665, 79662])
    materializer, processor = Mock(), Mock()
    processor.temporary_results.return_value = []
    processor.process.return_value = "Texto transcrito"
    if phase == "materializacion":
        materializer.materialize.side_effect = [RuntimeError(SECRET), None]
    else:
        processor.process.side_effect = [RuntimeError(SECRET), "Texto transcrito"]
    assert execute_external(
        "transcribe", source, materializer, processor, source, Workspace(tmp_path)
    ) == {"completed": 1, "failed": 1}
    failed = source.jobs.documents[(79665, "transcribe")]
    assert failed["error"]["phase"] == phase
    assert SECRET not in repr(failed)


def test_mongodb_pdf_still_passes_through_ssrf_policy(tmp_path):
    source = adapter([document(79665, "http://127.0.0.1/secreto.pdf")])
    processor = Mock()
    processor.temporary_results.return_value = []
    assert execute_external(
        "run", source, HTTPMaterializer(), processor, source, Workspace(tmp_path)
    ) == {"completed": 0, "failed": 1}
    processor.process.assert_not_called()
    assert source.jobs.documents[(79665, "run")]["error"]["phase"] == "materializacion"


@pytest.fixture
def driver(monkeypatch):
    client, db = Mock(), Mock()
    source = adapter().source
    jobs = Jobs()
    db.__getitem__ = Mock(return_value=source)
    db.get_collection.return_value = jobs
    client.__getitem__ = Mock(return_value=db)
    module = ModuleType("pymongo")
    module.MongoClient = Mock(return_value=client)
    errors = ModuleType("pymongo.errors")
    errors.DuplicateKeyError = DuplicateKeyError
    concern = ModuleType("pymongo.write_concern")
    concern.WriteConcern = Mock(return_value="confirmacion_mayoritaria")
    monkeypatch.setitem(sys.modules, "pymongo", module)
    monkeypatch.setitem(sys.modules, "pymongo.errors", errors)
    monkeypatch.setitem(sys.modules, "pymongo.write_concern", concern)
    monkeypatch.setenv("PDFSUM_MONGODB_URI", SECRET)
    return SimpleNamespace(
        module=module, client=client, db=db, jobs=jobs, source=source, concern=concern
    )


def test_factory_defaults_uri_and_lazy_writes(driver):
    source, store = build_mongodb_provider({"ids": [79665]})
    assert source is store
    driver.module.MongoClient.assert_called_once_with(
        SECRET, connect=False, serverSelectionTimeoutMS=10000
    )
    driver.client.__getitem__.assert_called_once_with("FIs_02_converted")
    driver.db.__getitem__.assert_called_once_with("mis")
    driver.db.get_collection.assert_called_once_with(
        "document_extraction_jobs", write_concern="confirmacion_mayoritaria"
    )
    assert not driver.jobs.operations
    driver.concern.WriteConcern.assert_called_once_with(w="majority")


@pytest.mark.parametrize(
    "options",
    [
        {"jobs_collection": "mis"},
        {"source_collection": "otra", "jobs_collection": "otra"},
        {"uri": SECRET},
        {"mongodb_uri": SECRET},
        {"database": ""},
    ],
)
def test_unsafe_configuration_is_rejected_before_client(driver, options):
    with pytest.raises(ValueError) as caught:
        build_mongodb_provider({"ids": [79665], **options})
    assert SECRET not in str(caught.value)
    driver.module.MongoClient.assert_not_called()


def test_factory_errors_are_sanitized(driver):
    driver.module.MongoClient.side_effect = ValueError(SECRET)
    with pytest.raises(MongoInfrastructureError) as caught:
        build_mongodb_provider({"ids": [79665]})
    assert SECRET not in str(caught.value)


def test_uri_cannot_be_omitted(driver, monkeypatch):
    monkeypatch.delenv("PDFSUM_MONGODB_URI")
    with pytest.raises(ValueError, match="PDFSUM_MONGODB_URI"):
        build_mongodb_provider({"ids": [79665]})
    driver.module.MongoClient.assert_not_called()


@pytest.mark.parametrize("use_file", [False, True])
def test_cli_ids_and_ids_file(tmp_path, driver, monkeypatch, use_file, capsys):
    options = ["--ids", 79665, 79662, 79667, 79665]
    if use_file:
        path = tmp_path / "ids.txt"
        path.write_text("79665\n79662 79667\n79665\n", encoding="utf-8")
        options = ["--ids-file", str(path)]
    processor = Mock()
    processor.temporary_results.return_value = []
    processor.process.return_value = "Texto principal"
    monkeypatch.setattr(
        "pdfsum.adapters.external_http.HTTPMaterializer", Mock(return_value=Mock())
    )
    monkeypatch.setattr(
        "pdfsum.adapters.external_processor.LocalInputProcessor",
        Mock(return_value=processor),
    )
    assert (
        main(
            [
                "external",
                "transcribe",
                "--provider",
                "mongodb",
                "--workspace",
                str(tmp_path),
                "--fake",
                *options,
            ]
        )
        == 1
    )
    assert set(driver.jobs.documents) == {
        (identifier, "transcribe") for identifier in (79665, 79662, 79667)
    }
    assert driver.jobs.documents[(79665, "transcribe")]["result"] == "Texto principal"
    output = capsys.readouterr().out
    assert "completados=1 fallidos=2" in output
    assert "clave" not in output and "secreto" not in output
    driver.client.close.assert_called_once()


def test_cli_collection_overrides(tmp_path, driver):
    assert (
        main(
            [
                "external",
                "transcribe",
                "--provider",
                "mongodb",
                "--workspace",
                str(tmp_path),
                "--fake",
                "--ids",
                "99999",
                "--database",
                "otra_base",
                "--source-collection",
                "entrada",
                "--jobs-collection",
                "trabajos",
            ]
        )
        == 1
    )
    driver.client.__getitem__.assert_called_once_with("otra_base")
    driver.db.__getitem__.assert_called_once_with("entrada")
    assert driver.db.get_collection.call_args.args == ("trabajos",)


def test_ids_options_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "external",
                "run",
                "--workspace",
                "datos",
                "--ids",
                "79665",
                "--ids-file",
                "ids.txt",
            ]
        )


@pytest.mark.parametrize(
    "config",
    [{}, {"ids": []}, {"ids": [""]}, {"ids": [79665], "ids_file": "archivo"}],
)
def test_explicit_nonempty_selection_required(config):
    with pytest.raises(ValueError):
        _selected_ids(config)


def test_ids_convert_to_integers_and_deduplicate(tmp_path):
    path = tmp_path / "ids.txt"
    path.write_text("0079665\n79665\n0079665\n", encoding="utf-8")
    assert _selected_ids({"ids_file": str(path)}) == [79665]


def test_invalid_ids_file_is_sanitized(tmp_path):
    with pytest.raises(ValueError, match="archivo de IDs") as caught:
        _selected_ids({"ids_file": tmp_path / "secreto"})
    assert "secreto" not in str(caught.value)
    path = tmp_path / "vacio.txt"
    path.write_text("")
    with pytest.raises(ValueError):
        _selected_ids({"ids_file": path})


def test_mongodb_summarize_is_explicit_and_never_connects(tmp_path, driver, capsys):
    assert (
        main(
            [
                "external",
                "summarize",
                "--provider",
                "mongodb",
                "--workspace",
                str(tmp_path),
                "--ids",
                79665,
                "--fake",
            ]
        )
        == 2
    )
    assert "fuente identificada de texto transcrito" in capsys.readouterr().out
    driver.module.MongoClient.assert_not_called()
    source = adapter()
    with pytest.raises(ValueError, match="texto transcrito"):
        list(source.pending("summarize"))
    assert not source.jobs.operations


def test_generic_imports_do_not_need_pymongo():
    code = """
import builtins
original = builtins.__import__
def sin_mongo(name, *args, **kwargs):
    if name.split('.')[0] == 'pymongo':
        raise AssertionError('El núcleo no debe cargar pymongo')
    return original(name, *args, **kwargs)
builtins.__import__ = sin_mongo
import pdfsum.external
import pdfsum.adapters.external_provider
import pdfsum.adapters.external_mongodb
import pdfsum.cli
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


@pytest.mark.parametrize(
    "value",
    [
        "1.5",
        "1e3",
        "abc",
        " 79665",
        "١٢٣",
        True,
        {},
        1.5,
        str(2**63),
        str(-(2**63) - 1),
    ],
)
def test_invalid_integer_ids_are_rejected_before_connecting(driver, value):
    with pytest.raises(ValueError, match="enteros BSON"):
        build_mongodb_provider({"ids": [value]})
    driver.module.MongoClient.assert_not_called()


def test_cli_never_uses_ids_from_config(tmp_path, driver, monkeypatch, capsys):
    monkeypatch.setattr(
        "pdfsum.cli.get_config_value",
        lambda key, default=None: (
            {"provider": "mongodb", "ids": [79665]} if key == "external" else default
        ),
    )
    assert main(["external", "transcribe", "--workspace", str(tmp_path), "--fake"]) == 2
    assert "--ids o --ids-file" in capsys.readouterr().out
    driver.module.MongoClient.assert_not_called()


def test_collection_config_is_supported(driver):
    build_mongodb_provider(
        {
            "ids": [79665],
            "database": "base_configurada",
            "source_collection": "entrada_configurada",
            "jobs_collection": "jobs_configurados",
        }
    )
    driver.client.__getitem__.assert_called_once_with("base_configurada")
    driver.db.__getitem__.assert_called_once_with("entrada_configurada")
    assert driver.db.get_collection.call_args.args == ("jobs_configurados",)


def test_unrelated_unique_index_failure_is_infrastructure(monkeypatch):
    source = adapter()
    monkeypatch.setattr(
        source.jobs, "update_one", Mock(side_effect=DuplicateKeyError(SECRET))
    )
    with pytest.raises(MongoInfrastructureError):
        list(source.pending("run"))


def test_close_failure_is_sanitized(tmp_path, driver, capsys):
    driver.client.close.side_effect = RuntimeError(SECRET)
    assert (
        main(
            [
                "external",
                "transcribe",
                "--provider",
                "mongodb",
                "--workspace",
                str(tmp_path),
                "--ids",
                "99999",
                "--fake",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "No se pudo cerrar" in output
    assert SECRET not in output


def test_operational_id_is_not_source_mongo_id():
    source = adapter([{"_id": 79665, "id": 99999, "electronic_address": [{"_u": URL}]}])
    assert list(source.pending("run")) == []
    assert source.jobs.documents[(79665, "run")]["error"]["code"] == "id_inexistente"


@pytest.mark.parametrize("entry", [None, {}, {"_u": []}, "https://ejemplo/a.pdf"])
def test_malformed_resource_entries_are_skipped(entry):
    assert _select_pdf({"electronic_address": [entry, {"_u": URL}]}) == URL
