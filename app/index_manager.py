import json
import os
import re
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import faiss

from app.config import Settings
from app.ingestion import (
    MAX_ANSWER_LENGTH,
    MAX_ID_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_SOURCE_LENGTH,
    PROVENANCE_STATUSES,
    KnowledgeEntry,
    KnowledgeImportError,
    ProvenanceRecord,
    format_dataset_id,
    load_faq_json,
    load_knowledge,
    load_provenance_json,
)
from app.providers import EmbeddingProvider, build_embedding_provider
from app.vector_store import FAISSVectorStore


MANIFEST_SCHEMA_VERSION = 1
INDEX_METADATA_SCHEMA_VERSION = 1
PROVENANCE_SCHEMA_VERSION = 1
LEGACY_VERSION = "legacy"
_VERSION_PATTERN = re.compile(r"^v\d{8}T\d{12}Z-[0-9a-f]{32}$")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


@dataclass
class BuildReport:
    selected_source: str
    records_read: int = 0
    accepted: int = 0
    rejected: int = 0
    exact_duplicates: int = 0
    embeddings_generated: int = 0
    new_version_id: str | None = None
    activation_succeeded: bool = False
    active_version_before: str | None = None
    active_version_after: str | None = None
    error_stage: str | None = None
    error_type: str | None = None
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["diagnostics"] = list(self.diagnostics)
        return result


@dataclass(frozen=True)
class LoadedKnowledgeSource:
    entries: list[KnowledgeEntry]
    dataset_id: str
    provenance: list[ProvenanceRecord] | None


class IndexOperationError(RuntimeError):
    def __init__(self, stage: str, cause: Exception, report: BuildReport | None = None):
        super().__init__(f"Index operation failed during {stage} ({type(cause).__name__}).")
        self.stage = stage
        self.cause_type = type(cause).__name__
        self.report = report


def _version_directory(settings: Settings, version_id: str) -> Path:
    if not _VERSION_PATTERN.fullmatch(version_id):
        raise ValueError("Invalid index version identifier.")
    return settings.effective_index_versions_dir / version_id


def _has_version_artifacts(settings: Settings) -> bool:
    directory = settings.effective_index_versions_dir
    return directory.is_dir() and any(
        entry.is_dir() and _VERSION_PATTERN.fullmatch(entry.name)
        for entry in directory.iterdir()
    )


def _read_manifest(settings: Settings) -> dict[str, Any] | None:
    path = settings.effective_active_index_manifest_path
    if not path.exists():
        if settings.effective_index_migration_marker_path.exists() or _has_version_artifacts(
            settings
        ):
            raise ValueError(
                "Active index manifest is missing after versioned index activation."
            )
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Active index manifest is unreadable ({type(exc).__name__}).") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or not {"schema_version", "active_version", "previous_version"}.issubset(manifest)
        or not isinstance(manifest.get("active_version"), str)
        or not (
            manifest["active_version"] == LEGACY_VERSION
            or _VERSION_PATTERN.fullmatch(manifest["active_version"])
        )
    ):
        raise ValueError("Active index manifest has an invalid schema or version.")
    previous = manifest.get("previous_version")
    if previous is not None and not (
        isinstance(previous, str)
        and (previous == LEGACY_VERSION or _VERSION_PATTERN.fullmatch(previous))
    ):
        raise ValueError("Active index manifest has an invalid previous version.")
    return manifest


def _validate_metadata_records(metadata: dict[str, Any], index: faiss.Index) -> None:
    if (
        type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != INDEX_METADATA_SCHEMA_VERSION
    ):
        raise ValueError("Unsupported index metadata schema.")
    count = metadata.get("record_count")
    dimension = metadata.get("dimension")
    records = metadata.get("records")
    embedding = metadata.get("embedding")
    if type(count) is not int or count <= 0 or count != index.ntotal:
        raise ValueError("FAISS vector count does not match metadata.")
    if type(dimension) is not int or dimension <= 0 or dimension != index.d:
        raise ValueError("FAISS vector dimensions do not match metadata.")
    if (
        not isinstance(embedding, dict)
        or not isinstance(embedding.get("provider"), str)
        or not embedding["provider"]
        or not isinstance(embedding.get("model"), str)
        or not embedding["model"]
    ):
        raise ValueError("Embedding provider/model metadata is incomplete.")
    if not isinstance(metadata.get("created_at"), str) or not metadata["created_at"]:
        raise ValueError("Index creation timestamp is missing.")
    try:
        datetime.fromisoformat(metadata["created_at"])
    except ValueError as exc:
        raise ValueError("Index creation timestamp is invalid.") from exc
    if not isinstance(metadata.get("source"), str) or not metadata["source"]:
        raise ValueError("Index source metadata is missing.")
    if not isinstance(metadata.get("version_id"), str) or not _VERSION_PATTERN.fullmatch(
        metadata["version_id"]
    ):
        raise ValueError("Index version metadata is missing or invalid.")
    if not isinstance(records, list) or len(records) != count:
        raise ValueError("Index record metadata is incomplete.")

    dataset_id = metadata.get("dataset_id")
    if "dataset_id" in metadata and (
        not isinstance(dataset_id, str) or not dataset_id.strip()
    ):
        raise ValueError("Index dataset identifier is invalid.")
    _validate_record_entries(
        records,
        require_ids=True,
        dataset_id=dataset_id if isinstance(dataset_id, str) else None,
    )
    if "provenance" in metadata:
        reference = metadata["provenance"]
        if (
            not isinstance(reference, dict)
            or set(reference) != {"schema_version", "file", "dataset_id", "record_count"}
            or type(reference.get("schema_version")) is not int
            or reference["schema_version"] != PROVENANCE_SCHEMA_VERSION
            or reference.get("file") != "provenance.json"
            or not isinstance(reference.get("dataset_id"), str)
            or reference["dataset_id"] != dataset_id
            or type(reference.get("record_count")) is not int
            or reference["record_count"] != count
        ):
            raise ValueError("Index provenance reference is invalid.")


def _validate_record_entries(
    records: list[Any], *, require_ids: bool, dataset_id: str | None = None
) -> None:
    seen_ids: set[str] = set()
    seen_content: set[tuple[str, str]] = set()
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Knowledge metadata record {position} is invalid.")
        question, answer, source = (
            record.get("question"),
            record.get("answer"),
            record.get("source"),
        )
        if not all(isinstance(value, str) and value.strip() for value in (question, answer, source)):
            raise ValueError(f"Knowledge metadata record {position} is incomplete.")
        record_id = record.get("faq_id") if dataset_id is not None else record.get("id")
        if require_ids and (
            not isinstance(record_id, str)
            or not record_id
            or len(record_id) > MAX_ID_LENGTH
            or not _ID_PATTERN.fullmatch(record_id)
        ):
            raise ValueError(f"Knowledge metadata record {position} has an invalid id.")
        if dataset_id is not None and record.get("dataset_id") != dataset_id:
            raise ValueError(f"Knowledge metadata record {position} has a mismatched dataset id.")
        if dataset_id is not None and "id" in record:
            raise ValueError(f"Knowledge metadata record {position} uses a legacy id field.")
        if (
            len(question) > MAX_QUESTION_LENGTH
            or len(answer) > MAX_ANSWER_LENGTH
            or len(source) > MAX_SOURCE_LENGTH
        ):
            raise ValueError(f"Knowledge metadata record {position} exceeds the supported schema.")
        content_key = (question.casefold(), answer.casefold())
        if (require_ids and record_id in seen_ids) or content_key in seen_content:
            raise ValueError(f"Index metadata record {position} is duplicated.")
        if require_ids:
            seen_ids.add(record_id)
        seen_content.add(content_key)


def _validate_provenance_document(
    document: Any, metadata: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    reference = metadata["provenance"]
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "dataset_id", "records"}
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != PROVENANCE_SCHEMA_VERSION
        or document.get("dataset_id") != reference["dataset_id"]
        or not isinstance(document.get("records"), list)
        or len(document["records"]) != reference["record_count"]
    ):
        raise ValueError("Version provenance sidecar has an invalid schema.")

    metadata_records = {
        (record["dataset_id"], record["faq_id"]): record
        for record in metadata["records"]
    }
    provenance_records: dict[tuple[str, str], dict[str, Any]] = {}
    required_fields = {
        "faq_id",
        "source",
        "source_locator",
        "source_excerpt",
        "provenance_status",
        "owner_review_required",
        "dataset_type",
        "dataset_name",
        "notes",
        "dataset_id",
    }
    for position, record in enumerate(document["records"], start=1):
        if not isinstance(record, dict) or set(record) != required_fields:
            raise ValueError(f"Version provenance record {position} has an invalid schema.")
        faq_id = record.get("faq_id")
        dataset_id = record.get("dataset_id")
        if (
            not isinstance(faq_id, str)
            or not faq_id
            or not isinstance(dataset_id, str)
        ):
            raise ValueError(f"Version provenance record {position} has an invalid FAQ id.")
        if dataset_id != reference["dataset_id"]:
            raise ValueError(f"Version provenance record {position} has a mismatched dataset id.")
        record_key = (dataset_id, faq_id)
        if record_key in provenance_records or record_key not in metadata_records:
            raise ValueError(f"Version provenance record {position} has an invalid FAQ id.")
        metadata_record = metadata_records[record_key]
        if (
            metadata_record.get("dataset_id") != reference["dataset_id"]
        ):
            raise ValueError(f"Version provenance record {position} has a mismatched dataset id.")
        if not isinstance(record.get("source"), str) or record["source"] != metadata_record["source"]:
            raise ValueError(f"Version provenance record {position} has a mismatched source.")
        locator = record.get("source_locator")
        if (
            not isinstance(locator, dict)
            or set(locator) != {"path", "section"}
            or not all(isinstance(value, str) and value.strip() for value in locator.values())
        ):
            raise ValueError(f"Version provenance record {position} has an invalid locator.")
        locator_path = PurePosixPath(locator["path"])
        if (
            locator_path.is_absolute()
            or "\\" in locator["path"]
            or not locator_path.parts
            or any(part in {"", ".", ".."} for part in locator_path.parts)
        ):
            raise ValueError(f"Version provenance record {position} has an unsafe locator path.")
        excerpt_list = record.get("source_excerpt")
        if not isinstance(excerpt_list, list) or not excerpt_list or any(
            not isinstance(excerpt, dict)
            or set(excerpt) != {"label", "quote"}
            or not all(
                isinstance(value, str) and value.strip() for value in excerpt.values()
            )
            for excerpt in excerpt_list
        ):
            raise ValueError(f"Version provenance record {position} has invalid excerpts.")
        status = record.get("provenance_status")
        if not isinstance(status, str) or status not in PROVENANCE_STATUSES:
            raise ValueError(f"Version provenance record {position} has an invalid status.")
        if type(record.get("owner_review_required")) is not bool:
            raise ValueError(
                f"Version provenance record {position} has an invalid review flag."
            )
        if not all(
            isinstance(record.get(field), str) and record[field].strip()
            for field in ("dataset_type", "dataset_name")
        ):
            raise ValueError(f"Version provenance record {position} has invalid dataset fields.")
        try:
            expected_dataset_id = format_dataset_id(
                record["dataset_type"], record["dataset_name"]
            )
        except ValueError as exc:
            raise ValueError(
                f"Version provenance record {position} has invalid dataset identity."
            ) from exc
        if dataset_id != expected_dataset_id:
            raise ValueError(f"Version provenance record {position} dataset identity is invalid.")
        if not isinstance(record.get("notes"), str):
            raise ValueError(f"Version provenance record {position} has invalid notes.")
        provenance_records[record_key] = record

    if set(provenance_records) != set(metadata_records):
        raise ValueError("Version provenance FAQ IDs do not match index metadata.")
    return provenance_records


def _load_version_provenance(
    directory: Path, metadata: dict[str, Any]
) -> dict[str, dict[str, Any]] | None:
    if "provenance" not in metadata:
        return None
    try:
        document = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Version provenance sidecar is unreadable ({type(exc).__name__})."
        ) from exc
    return _validate_provenance_document(document, metadata)


def _validate_version(
    settings: Settings,
    version_id: str,
    *,
    expected_provider: str | None = None,
    expected_model: str | None = None,
) -> tuple[FAISSVectorStore, dict[str, Any]]:
    directory = _version_directory(settings, version_id)
    index_path = directory / "index.faiss"
    metadata_path = directory / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        index = faiss.read_index(str(index_path))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Index version is unreadable ({type(exc).__name__}).") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Versioned index metadata must be an object.")
    if metadata.get("version_id") != version_id:
        raise ValueError("Index metadata version does not match its directory.")
    _validate_metadata_records(metadata, index)
    embedding = metadata["embedding"]
    if expected_provider is not None and embedding["provider"] != expected_provider:
        raise ValueError("Index embedding provider does not match runtime configuration.")
    if expected_model is not None and embedding["model"] != expected_model:
        raise ValueError("Index embedding model does not match runtime configuration.")
    provenance_records = _load_version_provenance(directory, metadata)
    if provenance_records is not None:
        metadata["records"] = [
            {
                **record,
                "provenance": provenance_records[
                    (record["dataset_id"], record["faq_id"])
                ],
            }
            for record in metadata["records"]
        ]
    store = FAISSVectorStore(index, metadata["records"])
    return store, metadata


def _load_legacy(settings: Settings) -> FAISSVectorStore:
    store = FAISSVectorStore.load(settings.index_path, settings.metadata_path)
    if store.index.ntotal <= 0 or store.index.d <= 0:
        raise ValueError("Legacy FAISS index is empty or has invalid dimensions.")
    _validate_record_entries(store.metadata, require_ids=False)
    return store


def _load_version_selector(
    settings: Settings, version_id: str
) -> tuple[FAISSVectorStore, dict[str, Any] | None]:
    if version_id == LEGACY_VERSION:
        return _load_legacy(settings), None
    return _validate_version(
        settings,
        version_id,
        expected_provider=settings.embedding_provider,
        expected_model=settings.embedding_model,
    )


def load_active_index(settings: Settings) -> tuple[FAISSVectorStore, str | None]:
    manifest = _read_manifest(settings)
    if manifest is None:
        return _load_legacy(settings), None
    version_id = manifest["active_version"]
    store, _ = _load_version_selector(settings, version_id)
    return store, None if version_id == LEGACY_VERSION else version_id


def get_active_version(settings: Settings) -> str | None:
    manifest = _read_manifest(settings)
    if manifest is None:
        try:
            _load_legacy(settings)
        except FileNotFoundError:
            return None
        return LEGACY_VERSION
    active = manifest["active_version"]
    if active == LEGACY_VERSION:
        _load_legacy(settings)
    else:
        _validate_version(settings, active)
    return active


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_migration_marker(settings: Settings) -> None:
    path = settings.effective_index_migration_marker_path
    if path.exists():
        return
    _write_atomic_json(
        path,
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "initialized_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _write_manifest(settings: Settings, active: str, previous: str | None) -> None:
    path = settings.effective_active_index_manifest_path
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "active_version": active,
        "previous_version": previous,
    }
    _write_atomic_json(path, payload)


def _load_source(settings: Settings, source: str) -> LoadedKnowledgeSource:
    if source == "demo":
        directory = settings.data_dir
        entries = load_knowledge(directory)
    elif source == "real":
        directory = settings.real_knowledge_dir
        entries = load_faq_json(directory / "faqs.json")
    else:
        raise ValueError("Source must be 'demo' or 'real'.")

    provenance_path = directory / "provenance.json"
    if provenance_path.exists():
        dataset_id, provenance = load_provenance_json(provenance_path, entries)
    else:
        dataset_id, provenance = source, None
    return LoadedKnowledgeSource(entries, dataset_id, provenance)


def validate_source(settings: Settings, source: str) -> BuildReport:
    report = BuildReport(selected_source=source)
    try:
        loaded_source = _load_source(settings, source)
    except KnowledgeImportError as exc:
        report.records_read = exc.records_read
        report.accepted = exc.accepted
        report.rejected = exc.rejected
        report.exact_duplicates = exc.exact_duplicates
        report.error_stage = "validation"
        report.error_type = type(exc).__name__
        report.diagnostics = exc.diagnostics
        raise IndexOperationError("validation", exc, report) from exc
    report.records_read = len(loaded_source.entries)
    report.accepted = len(loaded_source.entries)
    return report


def build_index(
    settings: Settings,
    source: str,
    embedding_provider: EmbeddingProvider | None = None,
) -> BuildReport:
    report = BuildReport(selected_source=source)
    stage = "active_version_check"
    staging_directory: Path | None = None
    try:
        report.active_version_before = get_active_version(settings)
        stage = "validation"
        try:
            loaded_source = _load_source(settings, source)
        except KnowledgeImportError as exc:
            report.records_read = exc.records_read
            report.accepted = exc.accepted
            report.rejected = exc.rejected
            report.exact_duplicates = exc.exact_duplicates
            report.diagnostics = exc.diagnostics
            raise
        entries = loaded_source.entries
        report.records_read = len(entries)
        report.accepted = len(entries)

        stage = "embeddings"
        provider = (
            embedding_provider
            if embedding_provider is not None
            else build_embedding_provider(settings)
        )
        vectors = provider.embed([entry.embedding_text for entry in entries])
        report.embeddings_generated = len(vectors)

        stage = "index_generation"
        store = FAISSVectorStore.from_embeddings(entries, vectors)
        version_id = datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%S%fZ-") + uuid.uuid4().hex
        report.new_version_id = version_id
        staging_directory = settings.effective_index_versions_dir / f".staging-{version_id}"
        final_directory = _version_directory(settings, version_id)
        staging_directory.mkdir(parents=True, exist_ok=False)
        metadata = {
            "schema_version": INDEX_METADATA_SCHEMA_VERSION,
            "version_id": version_id,
            "record_count": len(entries),
            "dimension": store.index.d,
            "embedding": {
                "provider": settings.embedding_provider,
                "model": settings.embedding_model,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "dataset_id": loaded_source.dataset_id,
            "records": [
                {
                    "dataset_id": loaded_source.dataset_id,
                    "faq_id": entry.id,
                    "question": entry.question,
                    "answer": entry.answer,
                    "source": entry.source,
                }
                for entry in entries
            ],
        }
        if loaded_source.provenance is not None:
            metadata["provenance"] = {
                "schema_version": PROVENANCE_SCHEMA_VERSION,
                "file": "provenance.json",
                "dataset_id": loaded_source.dataset_id,
                "record_count": len(loaded_source.provenance),
            }
        store.save(
            staging_directory / "index.faiss",
            staging_directory / "metadata.json",
            metadata,
        )
        if loaded_source.provenance is not None:
            stage = "provenance_publication"
            (staging_directory / "provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": PROVENANCE_SCHEMA_VERSION,
                        "dataset_id": loaded_source.dataset_id,
                        "records": [
                            record.as_dict() for record in loaded_source.provenance
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        _validate_directory(
            staging_directory,
            metadata,
            store.index,
            settings.embedding_provider,
            settings.embedding_model,
        )
        os.replace(staging_directory, final_directory)
        staging_directory = None

        stage = "version_validation"
        _validate_version(
            settings,
            version_id,
            expected_provider=settings.embedding_provider,
            expected_model=settings.embedding_model,
        )
        stage = "manifest_activation"
        _write_migration_marker(settings)
        _write_manifest(settings, version_id, report.active_version_before)
        report.activation_succeeded = True
        report.active_version_after = version_id
        return report
    except Exception as exc:
        report.error_stage = stage if not isinstance(exc, KnowledgeImportError) else "validation"
        report.error_type = type(exc).__name__
        if isinstance(exc, KnowledgeImportError) and not report.diagnostics:
            report.diagnostics = exc.diagnostics
        if report.active_version_after is None:
            try:
                report.active_version_after = get_active_version(settings)
            except Exception:
                report.active_version_after = report.active_version_before
        raise IndexOperationError(report.error_stage, exc, report) from exc
    finally:
        if staging_directory is not None:
            shutil.rmtree(staging_directory, ignore_errors=True)


def _validate_directory(
    directory: Path,
    metadata: dict[str, Any],
    expected_index: faiss.Index,
    expected_provider: str,
    expected_model: str,
) -> None:
    try:
        disk_metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        disk_index = faiss.read_index(str(directory / "index.faiss"))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Staged index is unreadable ({type(exc).__name__}).") from exc
    if not isinstance(disk_metadata, dict):
        raise ValueError("Staged index metadata must be an object.")
    if disk_metadata != metadata or disk_index.ntotal != expected_index.ntotal or disk_index.d != expected_index.d:
        raise ValueError("Staged index files do not match generated metadata and vectors.")
    if not _VERSION_PATTERN.fullmatch(disk_metadata.get("version_id", "")):
        raise ValueError("Staged index version identifier is invalid.")
    _validate_metadata_records(disk_metadata, disk_index)
    _load_version_provenance(directory, disk_metadata)
    if (
        disk_metadata["embedding"]["provider"] != expected_provider
        or disk_metadata["embedding"]["model"] != expected_model
    ):
        raise ValueError("Staged index embedding configuration does not match.")


def rollback_index(settings: Settings) -> str:
    manifest = _read_manifest(settings)
    if manifest is None:
        raise ValueError("No versioned active index is available to roll back.")
    active = manifest["active_version"]
    previous = manifest.get("previous_version")
    if previous is None:
        raise ValueError("No previous valid index version is recorded.")
    _load_version_selector(settings, previous)
    _write_manifest(settings, previous, active)
    return previous
