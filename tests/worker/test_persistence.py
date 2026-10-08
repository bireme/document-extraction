"""Pruebas aisladas: nunca se conectan a MongoDB ni HTTP reales."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import mongomock
import pytest
from pymongo.errors import AutoReconnect

import pdfsum_worker as worker
from result_mapper import MappingError, map_result
from result_publication import publish


@pytest.fixture
def dbs():
    client = mongomock.MongoClient(tz_aware=True)
    source, jobs, results = (
        client.origen.mis,
        client.jobs.jobs,
        client.resultados.abstracts,
    )
    jobs.create_index([("id", 1), ("command", 1)], unique=True)
    results.create_index("id", unique=True)
    source.insert_one(
        {"id": 75798, "electronic_address": [{"_u": "https://example.org/a.pdf"}]}
    )
    return source, jobs, results


@pytest.fixture
def config():
    return {
        "database": "resultados",
        "collection": "abstracts",
        "source_collection": "mis",
        "source_database": "origen",
        "prefix": "mis-",
        "format": "bireme",
    }


def original(**kwargs):
    return {
        "contract_version": "2.0",
        "ai_extracted_abstract": [],
        "ai_generated_abstract": None,
        **kwargs,
    }


def mapped(result, **kwargs):
    return map_result(
        result,
        source_id=75798,
        source_collection="mis",
        prefix=kwargs.get("prefix", "mis-"),
    )


@pytest.mark.parametrize(
    "lang,normalized",
    [("pt", "pt"), ("es", "es"), ("por", "pt"), ("spa", "es"), ("eng", "en")],
)
def test_extracted(lang, normalized):
    text = "  Resumen íntegro.\nOtra línea.  "
    assert (
        mapped(original(ai_extracted_abstract=[{"lang": lang, "text": text}]))[
            "ab_extracted_ia_" + normalized
        ]
        == text
    )


def test_languages_and_original():
    result = original(
        ai_extracted_abstract=[
            {"lang": "pt", "text": "Português"},
            {"lang": "es", "text": "Español"},
        ]
    )
    before = deepcopy(result)
    doc = mapped(result, prefix="otro-")
    assert doc["id"] == "otro-75798"
    assert doc["meta"]["source_id"] == 75798
    assert doc["ab_extracted_ia_pt"] == "Português"
    assert doc["ab_extracted_ia_es"] == "Español"
    assert "ai_extracted_abstract" not in doc
    assert result == before


def test_generated():
    assert (
        mapped(original(idioma_principal="por", ai_generated_abstract="Gerado"))[
            "ab_created_ia_pt"
        ]
        == "Gerado"
    )


@pytest.mark.parametrize(
    "result",
    [
        original(),
        original(ai_generated_abstract="  "),
        original(ai_extracted_abstract=[{"text": ""}]),
    ],
)
def test_no_abstract(result):
    assert set(mapped(result)) == {"id", "meta"}


@pytest.mark.parametrize("lang", [None, "zzz", "pt.$x", "pt\x00", 123])
def test_unknown_language(lang):
    with pytest.raises(MappingError):
        mapped(original(idioma_principal=lang, ai_generated_abstract="Texto"))


def test_duplicates():
    with pytest.raises(MappingError, match="mismo idioma"):
        mapped(
            original(
                ai_extracted_abstract=[
                    {"lang": "pt", "text": "Uno"},
                    {"lang": "por", "text": "Dos"},
                ]
            )
        )


def run(dbs, config, result=None, command="run", session=None):
    source, jobs, results = dbs
    worker.prepare_job(jobs, 75798, command)
    if session is None:
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {
            "id": 75798,
            "command": command,
            "status": "completed",
            "result": result,
        }
    status = worker.process_one(
        source,
        jobs,
        session,
        "http://api/api/pdfsum",
        75798,
        command,
        input_mode="url",
        input_folder=None,
        max_attempts=3,
        connect_timeout=1,
        read_timeout=2,
        results=results,
        publication_config=config,
    )
    return status, session


def test_two_copies_idempotence_source_unchanged(dbs, config):
    source, jobs, results = dbs
    before = list(source.find())
    raw = original(
        ai_extracted_abstract=[
            {"lang": "pt", "text": "Texto", "header": "RESUMO", "keywords": ""}
        ]
    )
    status, session = run(dbs, config, raw)
    assert status == "completed"
    assert jobs.find_one()["result"] == raw
    assert jobs.find_one()["id"] == 75798
    assert jobs.find_one()["publication"]["status"] == "published"
    assert results.find_one()["ab_extracted_ia_pt"] == "Texto"
    assert list(source.find()) == before
    run(dbs, config, raw, session=session)
    assert session.post.call_count == 1
    assert results.count_documents({}) == 1
    assert session.post.call_args.kwargs["json"]["id"] == 75798


def test_failure_retry_no_http(dbs, config, monkeypatch):
    _, jobs, results = dbs
    replace = results.replace_one
    monkeypatch.setattr(
        results, "replace_one", Mock(side_effect=AutoReconnect("secreto"))
    )
    raw = original(ai_generated_abstract="Texto", idioma_principal="pt")
    status, session = run(dbs, config, raw)
    assert status == "publication_failed"
    assert jobs.find_one()["result"] == raw
    assert "secreto" not in jobs.find_one()["publication"]["error"]
    monkeypatch.setattr(results, "replace_one", replace)
    assert run(dbs, config, session=session)[0] == "completed"
    assert session.post.call_count == 1
    assert jobs.find_one()["attempts"] == 1
    assert jobs.find_one()["publication"]["attempts"] == 2


def test_mapping_failure_keeps_original(dbs, config):
    raw = original(
        ai_extracted_abstract=[
            {"lang": "pt", "text": "Uno"},
            {"lang": "pt", "text": "Dos"},
        ]
    )
    assert run(dbs, config, raw)[0] == "publication_failed"
    assert dbs[1].find_one()["result"] == raw
    assert dbs[2].count_documents({}) == 0


def test_replacement_and_older_version(dbs, config):
    _, jobs, results = dbs
    run(
        dbs,
        config,
        original(ai_extracted_abstract=[{"lang": "es", "text": "Anterior"}]),
    )
    old = jobs.find_one()
    jobs.update_one(
        {},
        {
            "$set": {
                "result": original(ai_generated_abstract="Novo", idioma_principal="pt"),
                "publication.status": "pending",
                "publication.revision": "nueva",
                "publication.version": old["publication"]["version"]
                + timedelta(seconds=1),
            }
        },
    )
    assert (
        publish(jobs, results, {"id": 75798, "command": "run"}, config) == "published"
    )
    assert "ab_extracted_ia_es" not in results.find_one()
    old["publication"]["status"] = "pending"
    jobs.replace_one({"_id": old["_id"]}, old)
    assert (
        publish(jobs, results, {"id": 75798, "command": "run"}, config) == "superseded"
    )
    assert results.find_one()["ab_created_ia_pt"] == "Novo"


@pytest.mark.parametrize(
    "command,raw",
    [
        ("extract-abstracts", {"abstracts": [{"lang": "pt", "text": "Texto"}]}),
        ("transcribe", {"text": "Transcripción"}),
    ],
)
def test_other_commands(dbs, config, command, raw):
    assert run(dbs, config, raw, command)[0] == "completed"
    assert dbs[1].find_one()["result"] == raw
    assert dbs[1].find_one()["publication"]["status"] == "disabled"
    assert dbs[2].count_documents({}) == 0


@pytest.mark.parametrize(
    "http,payload",
    [
        (500, {"id": 75798, "command": "run", "status": "failed"}),
        (200, {"id": 1, "command": "run", "status": "completed"}),
        (200, []),
        (502, {"id": 75798, "command": "run", "status": "completed", "result": {}}),
    ],
)
def test_api_failure(dbs, config, http, payload):
    session = Mock()
    session.post.return_value.status_code = http
    session.post.return_value.json.return_value = payload
    assert run(dbs, config, session=session)[0] == "failed"
    assert "result" not in dbs[1].find_one()
    assert dbs[2].count_documents({}) == 0


def test_resume_after_result_write(dbs, config):
    _, jobs, results = dbs
    worker.prepare_job(jobs, 75798, "run")
    job, token = worker.claim_job(jobs, 75798, "run", 3)
    worker.save_completed(
        jobs, 75798, "run", token, original(), worker.make_publication(job, config)
    )
    session = Mock()
    assert run(dbs, config, session=session)[0] == "completed"
    session.post.assert_not_called()
    # Simula interrupción después del replace, antes de confirmar el job.
    jobs.update_one(
        {},
        {
            "$set": {
                "publication.status": "publishing",
                "publication.token": "perdido",
                "publication.lease_until": worker.utcnow() - timedelta(seconds=1),
            }
        },
    )
    assert run(dbs, config, session=session)[0] == "completed"
    assert results.count_documents({}) == 1
    session.post.assert_not_called()


def test_recover_processing_and_fencing(dbs):
    jobs = dbs[1]
    worker.prepare_job(jobs, 75798, "run")
    _, token = worker.claim_job(jobs, 75798, "run", 3)
    assert not worker.recover_stale_job(
        jobs, 75798, "run", stale_after=timedelta(minutes=60)
    )
    jobs.update_one(
        {}, {"$set": {"lease_until": worker.utcnow() - timedelta(seconds=1)}}
    )
    assert worker.recover_stale_job(
        jobs, 75798, "run", stale_after=timedelta(minutes=60)
    )
    job, new_token = worker.claim_job(jobs, 75798, "run", 3)
    assert job["attempts"] == 2
    with pytest.raises(RuntimeError):
        worker.save_completed(jobs, 75798, "run", token, original())
    worker.save_completed(jobs, 75798, "run", new_token, original())


def test_configuration(monkeypatch):
    for key, value in {
        "SOURCE_DATABASE": "origen",
        "JOBS_DATABASE": "jobs",
        "RESULTS_DATABASE": "resultados",
    }.items():
        monkeypatch.setenv("PDFSUM_" + key, value)
    args = worker.build_parser().parse_args(["--ids", "75798"])
    assert [db for db, _ in worker.collections_config(args)] == [
        "origen",
        "jobs",
        "resultados",
    ]
    args.jobs_database, args.jobs_collection = "origen", "mis"
    with pytest.raises(ValueError):
        worker.collections_config(args)


def test_legacy_database(monkeypatch):
    for key in ("SOURCE_DATABASE", "JOBS_DATABASE", "RESULTS_DATABASE"):
        monkeypatch.delenv("PDFSUM_" + key, raising=False)
    args = worker.build_parser().parse_args(
        ["--ids", "75798", "--database", "heredada"]
    )
    assert worker.collections_config(args)[:2] == [
        ("heredada", "mis"),
        ("heredada", "document_extraction_jobs"),
    ]


def test_size_limit(dbs, config, monkeypatch):
    monkeypatch.setattr("result_publication.MAX_DOCUMENT_BYTES", 1000)
    assert run(dbs, config, original(ai_generated_abstract="x" * 2000))[0] == "failed"
    assert dbs[1].find_one()["error"]["code"] == "resultado_bson_excedido"


def test_retry_cli_without_api(dbs, config, monkeypatch):
    raw = original(idioma_principal="no", ai_generated_abstract="Texto")
    run(dbs, config, raw)
    dbs[1].update_one({}, {"$set": {"result.idioma_principal": "pt"}})
    monkeypatch.setattr(worker, "MongoClient", lambda *a, **kw: dbs[0].database.client)
    monkeypatch.setenv("PDFSUM_MONGODB_URI", "mongodb://simulado")
    monkeypatch.setattr(
        worker.requests, "Session", Mock(side_effect=AssertionError("No invocar HTTP"))
    )
    assert (
        worker.main(
            [
                "--retry-publications",
                "--source-database",
                "origen",
                "--jobs-database",
                "jobs",
                "--jobs-collection",
                "jobs",
                "--results-database",
                "resultados",
                "--results-collection",
                "abstracts",
                "--result-id-prefix",
                "mis-",
            ]
        )
        == 0
    )


def test_live_publication_claim_not_stolen(dbs, config):
    run(dbs, config, original())
    jobs = dbs[1]
    jobs.update_one(
        {},
        {
            "$set": {
                "publication.status": "publishing",
                "publication.token": "vigente",
                "publication.lease_until": worker.utcnow() + timedelta(minutes=1),
            }
        },
    )
    assert (
        publish(jobs, dbs[2], {"id": 75798, "command": "run"}, config) == "publishing"
    )
    assert jobs.find_one()["publication"]["token"] == "vigente"


def test_legacy_completed_without_publication(dbs, config):
    dbs[1].insert_one(
        {
            "id": 75798,
            "command": "run",
            "status": "completed",
            "result": original(),
            "finished_at": worker.utcnow(),
            "attempts": 1,
        }
    )
    session = Mock()
    assert run(dbs, config, session=session)[0] == "completed"
    session.post.assert_not_called()


def test_destination_change_rejected(dbs, config):
    run(dbs, config, original())
    before = dbs[2].find_one()
    dbs[1].update_one({}, {"$set": {"publication.status": "pending"}})
    assert (
        publish(
            dbs[1],
            dbs[2],
            {"id": 75798, "command": "run"},
            {**config, "prefix": "otro-"},
        )
        == "failed"
    )
    assert dbs[2].find_one() == before


def test_equal_version_conflict(dbs, config):
    run(dbs, config, original())
    before = dbs[2].find_one()
    dbs[1].update_one(
        {}, {"$set": {"publication.status": "pending", "publication.revision": "otra"}}
    )
    assert publish(dbs[1], dbs[2], {"id": 75798, "command": "run"}, config) == "failed"
    assert dbs[2].find_one() == before


def test_attempts_exhausted(dbs, config):
    session = Mock()
    session.post.side_effect = worker.requests.Timeout()
    for _ in range(5):
        assert run(dbs, config, session=session)[0] == "failed"
    assert session.post.call_count == 3


def test_folder_does_not_query_source(dbs, config):
    worker.prepare_job(dbs[1], 75798, "transcribe")
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {
        "id": 75798,
        "command": "transcribe",
        "status": "completed",
        "result": {"text": "Texto"},
    }
    source = Mock()
    assert (
        worker.process_one(
            source,
            dbs[1],
            session,
            "http://api.invalid",
            75798,
            "transcribe",
            input_mode="folder",
            input_folder="carpeta",
            max_attempts=3,
            connect_timeout=1,
            read_timeout=1,
            results=dbs[2],
            publication_config=config,
        )
        == "completed"
    )
    source.find_one.assert_not_called()
    assert session.post.call_args.kwargs["json"] == {
        "id": 75798,
        "command": "transcribe",
        "folder": "carpeta",
    }


@pytest.mark.parametrize("value", ["1.0", "abc", str(2**63), "../1"])
def test_invalid_ids(value):
    with pytest.raises(ValueError):
        worker.parse_ids([value])


def test_safe_url_selection():
    doc = {
        "electronic_address": [
            {"_u": "http://example.org/a.pdf"},
            {"_u": "https://usuario:secreto@example.org/a.pdf"},
            {"_u": "https://example.org/b.pdf?token=privado"},
        ]
    }
    assert worker.select_pdf(doc) == "https://example.org/b.pdf?token=privado"
    with pytest.raises(worker.SelectionError):
        worker.select_pdf({"electronic_address": [{"_u": "file:///a.pdf"}]})


def test_heartbeat_renews_without_sleep(dbs, monkeypatch):
    jobs = dbs[1]
    worker.prepare_job(jobs, 75798, "run")
    _, token = worker.claim_job(jobs, 75798, "run", 3)
    old = worker.utcnow() - timedelta(seconds=1)
    jobs.update_one({}, {"$set": {"lease_until": old}})
    event = Mock()
    event.wait.side_effect = [False, True]
    monkeypatch.setattr(worker, "Event", lambda: event)

    class ImmediateThread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

        def join(self, **kwargs):
            pass

    monkeypatch.setattr(worker, "Thread", ImmediateThread)
    with worker.heartbeat(jobs, 75798, "run", token, timedelta(minutes=60)):
        assert jobs.find_one()["lease_until"] > old
        assert not worker.recover_stale_job(
            jobs, 75798, "run", stale_after=timedelta(minutes=60)
        )


def test_bson_int64_identifier():
    from bson.int64 import Int64

    doc = map_result(
        original(), source_id=Int64(2**40), source_collection="mis", prefix="x-"
    )
    assert doc["meta"]["source_id"] == 2**40


def test_missing_contract_not_published():
    with pytest.raises(MappingError):
        mapped({"ai_extracted_abstract": []})


def test_legacy_without_date_cannot_overwrite(dbs, config):
    dbs[1].insert_one(
        {"id": 75798, "command": "run", "status": "completed", "result": original()}
    )
    assert run(dbs, config, session=Mock())[0] == "publication_failed"
    assert dbs[2].count_documents({}) == 0


def test_invalid_json_response(dbs, config):
    session = Mock()
    session.post.return_value.json.side_effect = ValueError("respuesta privada")
    assert run(dbs, config, session=session)[0] == "failed"
    assert dbs[1].find_one()["error"]["code"] == "respuesta_invalida"


def test_no_abstract_removes_old_fields(dbs, config):
    run(dbs, config, original(idioma_principal="pt", ai_generated_abstract="Anterior"))
    dbs[1].update_one(
        {}, {"$set": {"result": original(), "publication.status": "pending"}}
    )
    assert (
        publish(dbs[1], dbs[2], {"id": 75798, "command": "run"}, config) == "published"
    )
    assert set(dbs[2].find_one()) == {"_id", "id", "meta"}
