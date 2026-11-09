import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.index_manager import (
    IndexOperationError,
    build_index,
    load_active_index,
    rollback_index,
)
from app.ingestion import KnowledgeEntry
from app.vector_store import FAISSVectorStore


class FakeEmbeddings:
    def __init__(self, vectors=None, error=None):
        self.vectors = vectors
        self.error = error
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        if self.error:
            raise self.error
        return self.vectors or [[1.0, 0.0] for _ in texts]


def make_settings(tmp_path):
    data_dir = tmp_path / "demo"
    data_dir.mkdir()
    (data_dir / "faqs.json").write_text(
        json.dumps(
            [
                {
                    "question": "Fictional demo question",
                    "answer": "Fictional demo answer",
                    "source": "demo-source",
                }
            ]
        ),
        encoding="utf-8",
    )
    real_dir = tmp_path / "knowledge" / "real"
    real_dir.mkdir(parents=True)
    (real_dir / "faqs.json").write_text(
        json.dumps(
            {
                "faqs": [
                    {
                        "id": "real-one",
                        "question": "Fictional real-source question",
                        "answer": "Fictional real-source answer",
                        "source": "fictional handbook",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        app_env="test",
        llm_provider="proxyapi",
        proxyapi_api_key="",
        proxyapi_base_url="",
        proxyapi_model="mock",
        openai_api_key="",
        openai_model="mock",
        embedding_provider="proxyapi",
        embedding_api_key="",
        embedding_base_url="",
        embedding_model="fake-embedding-model",
        request_timeout=1,
        similarity_threshold=0.1,
        top_k=2,
        max_message_length=4000,
        cors_origins=(),
        data_dir=data_dir,
        index_path=tmp_path / "legacy.faiss",
        metadata_path=tmp_path / "legacy-metadata.json",
        memory_db_path=tmp_path / "memory.sqlite3",
        real_knowledge_dir=real_dir,
        index_versions_dir=tmp_path / "versions",
        active_index_manifest_path=tmp_path / "active.json",
    )


def make_legacy_index(settings):
    store = FAISSVectorStore.from_embeddings(
        [KnowledgeEntry("Legacy question", "Legacy answer", "legacy.json")],
        [[1.0, 0.0]],
    )
    store.save(settings.index_path, settings.metadata_path)


def write_test_provenance(
    settings, *, mutate=None, dataset_type="pilot", dataset_name="test-dataset"
):
    faq = json.loads(
        (settings.real_knowledge_dir / "faqs.json").read_text(encoding="utf-8")
    )["faqs"][0]
    record = {
        "id": faq["id"],
        "source": faq["source"],
        "source_locator": {"path": "cases.py", "section": "test case"},
        "source_excerpt": [{"label": "Excerpt", "quote": "A literal test quote."}],
        "provenance_status": "source_verified",
        "owner_review_required": True,
        "notes": "private test note",
    }
    if mutate:
        mutate(record)
    payload = {
        "dataset_type": dataset_type,
        "dataset_name": dataset_name,
        "records": [record],
    }
    (settings.real_knowledge_dir / "provenance.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def build_provenanced_version(settings, embeddings=None):
    write_test_provenance(settings)
    report = build_index(settings, "real", embeddings or FakeEmbeddings())
    return report, settings.index_versions_dir / report.new_version_id


def test_build_creates_valid_version_and_activates_selected_source(tmp_path):
    settings = make_settings(tmp_path)
    embeddings = FakeEmbeddings()

    report = build_index(settings, "real", embeddings)

    assert report.selected_source == "real"
    assert (report.records_read, report.accepted, report.rejected) == (1, 1, 0)
    assert report.embeddings_generated == 1
    assert report.activation_succeeded
    assert report.active_version_before is None
    assert report.active_version_after == report.new_version_id
    store, version = load_active_index(settings)
    assert version == report.new_version_id
    assert store.metadata[0]["faq_id"] == "real-one"
    assert store.metadata[0]["source"] == "fictional handbook"
    metadata = json.loads(
        (settings.index_versions_dir / version / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["record_count"] == 1
    assert metadata["dimension"] == 2
    assert metadata["embedding"] == {
        "provider": "proxyapi",
        "model": "fake-embedding-model",
    }
    assert settings.active_index_manifest_path.is_file()
    assert settings.effective_index_migration_marker_path.is_file()


def test_initial_legacy_load_is_allowed_without_manifest_or_marker(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)

    store, version = load_active_index(settings)

    assert version is None
    assert store.metadata[0]["question"] == "Legacy question"
    assert not settings.active_index_manifest_path.exists()
    assert not settings.effective_index_migration_marker_path.exists()


def test_missing_manifest_after_activation_fails_closed_across_reloads(tmp_path):
    settings = make_settings(tmp_path)
    build_index(settings, "real", FakeEmbeddings())
    settings.active_index_manifest_path.unlink()

    for _ in range(2):
        with pytest.raises(ValueError, match="manifest is missing"):
            load_active_index(settings)


def test_missing_manifest_with_version_artifacts_fails_without_marker(tmp_path):
    settings = make_settings(tmp_path)
    build_index(settings, "real", FakeEmbeddings())
    settings.active_index_manifest_path.unlink()
    settings.effective_index_migration_marker_path.unlink()

    with pytest.raises(ValueError, match="manifest is missing"):
        load_active_index(settings)


def test_demo_and_real_sources_are_never_combined(tmp_path):
    settings = make_settings(tmp_path)

    report = build_index(settings, "demo", FakeEmbeddings())

    store, _ = load_active_index(settings)
    assert report.selected_source == "demo"
    assert store.metadata[0]["source"] == "demo-source"
    assert "real-source" not in store.metadata[0]["answer"]


def test_invalid_source_fails_before_embedding_calls(tmp_path):
    settings = make_settings(tmp_path)
    source_path = settings.real_knowledge_dir / "faqs.json"
    source_path.write_text(
        json.dumps(
            [
                {"question": "Valid", "answer": "Valid answer"},
                {"question": "", "answer": "Invalid answer"},
            ]
        ),
        encoding="utf-8",
    )
    embeddings = FakeEmbeddings()

    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", embeddings)

    assert error.value.stage == "validation"
    assert error.value.report.records_read == 2
    assert error.value.report.accepted == 1
    assert error.value.report.rejected == 1
    assert embeddings.calls == []
    assert not settings.active_index_manifest_path.exists()


def test_duplicate_report_counts_rejected_duplicate_before_embedding(tmp_path):
    settings = make_settings(tmp_path)
    (settings.real_knowledge_dir / "faqs.json").write_text(
        json.dumps(
            [
                {"question": "Same", "answer": "Answer"},
                {"question": " same ", "answer": " answer "},
            ]
        ),
        encoding="utf-8",
    )
    embeddings = FakeEmbeddings()

    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", embeddings)

    assert error.value.report.exact_duplicates == 1
    assert error.value.report.rejected == 1
    assert embeddings.calls == []


def test_embedding_failure_preserves_previous_active_version(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)

    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", FakeEmbeddings(error=RuntimeError("private provider details")))

    assert error.value.stage == "embeddings"
    assert error.value.report.error_type == "RuntimeError"
    assert error.value.report.embeddings_generated == 0
    assert error.value.report.active_version_after == "legacy"
    assert load_active_index(settings)[1] is None
    assert not settings.effective_index_migration_marker_path.exists()


def test_embedding_count_and_dimension_mismatches_preserve_previous(tmp_path):
    settings = make_settings(tmp_path)
    previous = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    source_path = settings.real_knowledge_dir / "faqs.json"
    source_path.write_text(
        json.dumps(
            [
                {"question": "Question one", "answer": "Answer one"},
                {"question": "Question two", "answer": "Answer two"},
            ]
        ),
        encoding="utf-8",
    )

    for bad_vectors in ([[1.0, 0.0]], [[1.0, 0.0], [1.0, 0.0, 0.0]]):
        with pytest.raises(IndexOperationError) as error:
            build_index(settings, "real", FakeEmbeddings(vectors=bad_vectors))
        assert error.value.stage == "index_generation"
        assert error.value.report.active_version_after == previous
        assert load_active_index(settings)[1] == previous


def test_write_failure_preserves_previous_active_version(tmp_path, monkeypatch):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)

    def fail_save(*args, **kwargs):
        raise OSError("private filesystem detail")

    monkeypatch.setattr(FAISSVectorStore, "save", fail_save)
    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", FakeEmbeddings())

    assert error.value.stage == "index_generation"
    assert error.value.report.active_version_after == "legacy"
    assert load_active_index(settings)[1] is None
    assert not settings.effective_index_migration_marker_path.exists()


def test_provenance_write_failure_preserves_active_version_and_discards_staging(
    tmp_path, monkeypatch
):
    from pathlib import Path

    settings = make_settings(tmp_path)
    previous = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    write_test_provenance(settings)
    manifest_before = settings.active_index_manifest_path.read_bytes()
    original_write_text = Path.write_text

    def fail_provenance_write(path, data, *args, **kwargs):
        if path.name == "provenance.json" and path.parent.name.startswith(".staging-"):
            original_write_text(path, data[:1], *args, **kwargs)
            raise OSError("simulated sidecar write failure")
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_provenance_write)
    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", FakeEmbeddings())

    assert error.value.stage == "provenance_publication"
    assert settings.active_index_manifest_path.read_bytes() == manifest_before
    assert error.value.report.active_version_after == previous
    assert load_active_index(settings)[1] == previous
    assert not list(settings.index_versions_dir.glob(".staging-*"))
    assert error.value.report.new_version_id is not None
    assert not (
        settings.index_versions_dir / error.value.report.new_version_id
    ).exists()


def test_manifest_activation_failure_keeps_previous_active(tmp_path, monkeypatch):
    import os
    import app.index_manager as manager

    settings = make_settings(tmp_path)
    previous = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    original_replace = os.replace

    def fail_manifest_replace(source, destination):
        if destination == settings.active_index_manifest_path:
            raise OSError("private manifest detail")
        original_replace(source, destination)

    monkeypatch.setattr(manager.os, "replace", fail_manifest_replace)
    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", FakeEmbeddings())

    assert error.value.stage == "manifest_activation"
    assert error.value.report.active_version_after == previous
    assert load_active_index(settings)[1] == previous


def test_failure_after_marker_creation_fails_closed(tmp_path, monkeypatch):
    import app.index_manager as manager

    settings = make_settings(tmp_path)
    make_legacy_index(settings)

    def fail_manifest(*args, **kwargs):
        raise OSError("manifest publication failed")

    monkeypatch.setattr(manager, "_write_manifest", fail_manifest)
    with pytest.raises(IndexOperationError) as error:
        build_index(settings, "real", FakeEmbeddings())

    assert error.value.stage == "manifest_activation"
    assert settings.effective_index_migration_marker_path.is_file()
    assert not settings.active_index_manifest_path.exists()
    with pytest.raises(ValueError, match="manifest is missing"):
        load_active_index(settings)


@pytest.mark.parametrize(
    "record",
    [
        {"answer": "Answer", "source": "source"},
        {"question": "Question", "source": "source"},
        {"question": "Question", "answer": "Answer"},
        {"question": "", "answer": "Answer", "source": "source"},
        {"question": "Question", "answer": "", "source": "source"},
        {"question": "Question", "answer": "Answer", "source": ""},
        {"question": 1, "answer": "Answer", "source": "source"},
        {"question": "Question", "answer": [], "source": "source"},
        {"question": "Question", "answer": "Answer", "source": None},
    ],
)
def test_legacy_metadata_records_require_nonempty_string_fields(
    tmp_path, record
):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)
    settings.metadata_path.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(ValueError, match="metadata record"):
        load_active_index(settings)


def test_rollback_rejects_incomplete_legacy_without_changing_manifest(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)
    build_index(settings, "real", FakeEmbeddings())
    settings.metadata_path.write_text(
        json.dumps([{"question": "Legacy question", "source": "legacy.json"}]),
        encoding="utf-8",
    )
    manifest_before = settings.active_index_manifest_path.read_bytes()

    with pytest.raises(ValueError, match="metadata record"):
        rollback_index(settings)

    assert settings.active_index_manifest_path.read_bytes() == manifest_before


def test_legacy_index_is_preserved_as_rollback_target(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)

    report = build_index(settings, "real", FakeEmbeddings())

    assert report.active_version_before == "legacy"
    assert settings.index_path.is_file()
    assert settings.metadata_path.is_file()
    assert rollback_index(settings) == "legacy"
    store, version = load_active_index(settings)
    assert version is None
    assert store.metadata[0]["question"] == "Legacy question"


def test_rollback_switches_to_previous_version(tmp_path):
    settings = make_settings(tmp_path)
    first = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    second = build_index(settings, "real", FakeEmbeddings()).new_version_id

    assert rollback_index(settings) == first
    assert load_active_index(settings)[1] == first
    assert rollback_index(settings) == second
    assert load_active_index(settings)[1] == second


def test_invalid_legacy_metadata_fails_readiness(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)
    settings.metadata_path.write_text(
        json.dumps([{"question": "Legacy question", "source": "legacy.json"}]),
        encoding="utf-8",
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


@pytest.mark.parametrize("metadata_field", ["record_count", "dimension"])
def test_runtime_rejects_index_metadata_mismatch(tmp_path, metadata_field):
    settings = make_settings(tmp_path)
    version = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    metadata_path = settings.index_versions_dir / version / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata[metadata_field] += 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="match metadata"):
        load_active_index(settings)


def test_runtime_rejects_configured_embedding_model_mismatch(tmp_path):
    settings = make_settings(tmp_path)
    previous = build_index(settings, "demo", FakeEmbeddings()).new_version_id
    settings = replace(settings, embedding_model="different-model")

    with pytest.raises(ValueError, match="model does not match"):
        load_active_index(settings)
    report = build_index(settings, "real", FakeEmbeddings())

    assert report.active_version_before == previous
    assert report.activation_succeeded
    assert load_active_index(settings)[1] == report.new_version_id
    with pytest.raises(ValueError, match="model does not match"):
        rollback_index(settings)


def test_invalid_manifest_is_rejected_without_legacy_fallback(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)
    settings.active_index_manifest_path.write_text(
        '{"schema_version": 1, "active_version": "../legacy"}', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="manifest"):
        load_active_index(settings)


def test_startup_loads_active_version_and_readiness_stays_predictable(tmp_path):
    settings = make_settings(tmp_path)
    version = build_index(settings, "real", FakeEmbeddings()).new_version_id
    application = create_app(settings)

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").json() == {"status": "ready"}
        assert application.state.active_index_version == version
        assert application.state.vector_store.metadata[0]["faq_id"] == "real-one"


def test_invalid_manifest_keeps_liveness_and_fails_readiness(tmp_path):
    settings = make_settings(tmp_path)
    settings.active_index_manifest_path.write_text(
        '{"schema_version": 1, "active_version": "../legacy", "previous_version": null}',
        encoding="utf-8",
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


def test_versioned_provenance_sidecar_is_saved_validated_and_loaded(tmp_path):
    settings = make_settings(tmp_path)
    embeddings = FakeEmbeddings()

    report, version_dir = build_provenanced_version(settings, embeddings)
    store, version = load_active_index(settings)
    metadata = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    sidecar = json.loads((version_dir / "provenance.json").read_text(encoding="utf-8"))

    assert version == report.new_version_id
    assert metadata["dataset_id"] == "pilot:test-dataset"
    assert metadata["records"][0] == {
        "dataset_id": "pilot:test-dataset",
        "faq_id": "real-one",
        "question": "Fictional real-source question",
        "answer": "Fictional real-source answer",
        "source": "fictional handbook",
    }
    assert sidecar["records"][0]["faq_id"] == "real-one"
    assert store.metadata[0]["provenance"]["provenance_status"] == "source_verified"
    assert store.metadata[0]["provenance"]["notes"] == "private test note"
    assert embeddings.calls == [
        ["Fictional real-source question\nFictional real-source answer"]
    ]


def test_version_with_provenance_reference_rejects_missing_sidecar(tmp_path):
    settings = make_settings(tmp_path)
    _, version_dir = build_provenanced_version(settings)
    (version_dir / "provenance.json").unlink()

    with pytest.raises(ValueError, match="sidecar is unreadable"):
        load_active_index(settings)


def test_version_with_provenance_reference_rejects_invalid_json(tmp_path):
    settings = make_settings(tmp_path)
    _, version_dir = build_provenanced_version(settings)
    (version_dir / "provenance.json").write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="sidecar is unreadable"):
        load_active_index(settings)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: record.update(id="unknown-faq"), "FAQ id does not exist"),
        (lambda record: record.update(source="different-source"), "source does not match"),
        (
            lambda record: record.update(provenance_status="unverified-ish"),
            "provenance_status is unsupported",
        ),
    ],
)
def test_invalid_provenance_fails_before_embedding(
    tmp_path, mutation, message
):
    settings = make_settings(tmp_path)
    write_test_provenance(settings, mutate=mutation)
    embeddings = FakeEmbeddings()

    with pytest.raises(IndexOperationError, match="validation"):
        build_index(settings, "real", embeddings)

    assert embeddings.calls == []
    assert not settings.active_index_manifest_path.exists()


def test_ambiguous_dataset_identity_fails_before_embedding(tmp_path):
    settings = make_settings(tmp_path)
    write_test_provenance(settings, dataset_type="pilot:other")
    embeddings = FakeEmbeddings()

    with pytest.raises(IndexOperationError, match="validation"):
        build_index(settings, "real", embeddings)

    assert embeddings.calls == []
    assert not settings.active_index_manifest_path.exists()


def test_duplicate_provenance_ids_fail_before_embedding(tmp_path):
    settings = make_settings(tmp_path)
    write_test_provenance(settings)
    path = settings.real_knowledge_dir / "provenance.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["records"].append(payload["records"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")
    embeddings = FakeEmbeddings()

    with pytest.raises(IndexOperationError, match="validation"):
        build_index(settings, "real", embeddings)

    assert embeddings.calls == []


def test_provenance_dataset_id_mismatch_fails_version_loading(tmp_path):
    settings = make_settings(tmp_path)
    _, version_dir = build_provenanced_version(settings)
    path = version_dir / "provenance.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][0]["dataset_id"] = "pilot:other-dataset"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="mismatched dataset id"):
        load_active_index(settings)


def test_old_version_without_provenance_remains_loadable(tmp_path):
    settings = make_settings(tmp_path)
    report = build_index(settings, "real", FakeEmbeddings())
    metadata_path = settings.index_versions_dir / report.new_version_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("dataset_id")
    metadata["records"] = [
        {
            "id": record.pop("faq_id"),
            "question": record["question"],
            "answer": record["answer"],
            "source": record["source"],
        }
        for record in metadata["records"]
    ]
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    store, version = load_active_index(settings)

    assert version == report.new_version_id
    assert store.metadata[0]["id"] == "real-one"
    assert "provenance" not in store.metadata[0]


def test_rollback_restores_version_with_its_provenance(tmp_path):
    settings = make_settings(tmp_path)
    first_report, _ = build_provenanced_version(settings)
    (settings.real_knowledge_dir / "provenance.json").unlink()
    second_report = build_index(settings, "real", FakeEmbeddings())

    assert rollback_index(settings) == first_report.new_version_id
    store, version = load_active_index(settings)

    assert version == first_report.new_version_id
    assert store.metadata[0]["provenance"]["dataset_id"] == "pilot:test-dataset"
    assert second_report.new_version_id != first_report.new_version_id


def test_rollback_to_legacy_without_provenance_remains_supported(tmp_path):
    settings = make_settings(tmp_path)
    make_legacy_index(settings)
    build_index(settings, "real", FakeEmbeddings())

    assert rollback_index(settings) == "legacy"
    store, version = load_active_index(settings)

    assert version is None
    assert store.metadata[0]["question"] == "Legacy question"
    assert "provenance" not in store.metadata[0]


@pytest.mark.parametrize("corruption", ["missing", "invalid_json"])
def test_rollback_rejects_corrupt_provenance_without_changing_active_version(
    tmp_path, corruption
):
    settings = make_settings(tmp_path)
    first_report, first_directory = build_provenanced_version(settings)
    (settings.real_knowledge_dir / "provenance.json").unlink()
    active_version = build_index(settings, "real", FakeEmbeddings()).new_version_id
    sidecar_path = first_directory / "provenance.json"
    if corruption == "missing":
        sidecar_path.unlink()
    else:
        sidecar_path.write_text("{", encoding="utf-8")
    manifest_before = settings.active_index_manifest_path.read_bytes()

    with pytest.raises(ValueError, match="sidecar is unreadable"):
        rollback_index(settings)

    assert first_report.new_version_id != active_version
    assert settings.active_index_manifest_path.read_bytes() == manifest_before
    store, loaded_version = load_active_index(settings)
    assert loaded_version == active_version
    assert store.metadata[0]["faq_id"] == "real-one"
