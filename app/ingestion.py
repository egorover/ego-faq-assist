import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


MAX_QUESTION_LENGTH = 500
MAX_ANSWER_LENGTH = 10_000
MAX_SOURCE_LENGTH = 500
MAX_ID_LENGTH = 128
_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_DATASET_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
PROVENANCE_STATUSES = {
    "source_verified",
    "owner_approved",
    "insufficient_information",
    "owner_review_required",
}


@dataclass(frozen=True)
class KnowledgeEntry:
    question: str
    answer: str
    source: str
    id: str = ""

    @property
    def embedding_text(self) -> str:
        return f"{self.question}\n{self.answer}"


@dataclass(frozen=True)
class ProvenanceRecord:
    faq_id: str
    source: str
    source_locator: dict[str, str]
    source_excerpt: tuple[dict[str, str], ...]
    provenance_status: str
    owner_review_required: bool
    dataset_type: str
    dataset_name: str
    notes: str
    dataset_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "faq_id": self.faq_id,
            "source": self.source,
            "source_locator": self.source_locator,
            "source_excerpt": list(self.source_excerpt),
            "provenance_status": self.provenance_status,
            "owner_review_required": self.owner_review_required,
            "dataset_type": self.dataset_type,
            "dataset_name": self.dataset_name,
            "notes": self.notes,
            "dataset_id": self.dataset_id,
        }


class KnowledgeImportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        records_read: int = 0,
        accepted: int = 0,
        rejected: int = 0,
        exact_duplicates: int = 0,
        diagnostics: tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.records_read = records_read
        self.accepted = accepted
        self.rejected = rejected
        self.exact_duplicates = exact_duplicates
        self.diagnostics = diagnostics


def _normalize(value: Any, field: str, record_number: int, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"record {record_number}: '{field}' must be a non-empty string")
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if len(normalized) > maximum:
        raise ValueError(f"record {record_number}: '{field}' exceeds {maximum} characters")
    return normalized


def _record_id(question: str, answer: str) -> str:
    digest = hashlib.sha256(f"{question}\n{answer}".encode("utf-8")).hexdigest()[:24]
    return f"faq-{digest}"


def format_dataset_id(dataset_type: str, dataset_name: str) -> str:
    if (
        not isinstance(dataset_type, str)
        or not isinstance(dataset_name, str)
        or not _DATASET_COMPONENT_PATTERN.fullmatch(dataset_type)
        or not _DATASET_COMPONENT_PATTERN.fullmatch(dataset_name)
    ):
        raise ValueError(
            "dataset_type and dataset_name must contain only letters, digits, dots, underscores, or hyphens."
        )
    return f"{dataset_type}:{dataset_name}"


def _validated_entries(
    payload: Any, source_name: str, path: Path
) -> list[KnowledgeEntry]:
    if isinstance(payload, dict):
        payload = payload.get("faqs")
    if not isinstance(payload, list):
        raise KnowledgeImportError(
            f"{path} must contain a list of FAQ objects or an object with a 'faqs' list.",
            records_read=1,
            rejected=1,
            diagnostics=("record 1: expected a list of FAQ objects",),
        )

    seen_content: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    entries: list[KnowledgeEntry] = []
    diagnostics: list[str] = []
    duplicates = 0

    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            diagnostics.append(f"record {position}: expected an object")
            continue
        try:
            question = _normalize(
                item.get("question"), "question", position, MAX_QUESTION_LENGTH
            )
            answer = _normalize(item.get("answer"), "answer", position, MAX_ANSWER_LENGTH)
            source = _normalize(
                item.get("source", source_name), "source", position, MAX_SOURCE_LENGTH
            )
            raw_id = item.get("id")
            record_id = (
                _normalize(raw_id, "id", position, MAX_ID_LENGTH)
                if raw_id is not None
                else _record_id(question, answer)
            )
            if not _ID_PATTERN.fullmatch(record_id):
                raise ValueError(
                    f"record {position}: 'id' may contain only letters, digits, '.', '_', ':' or '-'"
                )
        except ValueError as exc:
            diagnostics.append(str(exc))
            continue

        content_key = (question.casefold(), answer.casefold())
        if content_key in seen_content:
            duplicates += 1
            diagnostics.append(f"record {position}: exact duplicate question/answer")
            continue
        if record_id in seen_ids:
            diagnostics.append(f"record {position}: duplicate id")
            continue
        seen_content.add(content_key)
        seen_ids.add(record_id)
        entries.append(KnowledgeEntry(question, answer, source, record_id))

    rejected = len(payload) - len(entries)
    if diagnostics or not entries:
        if not diagnostics:
            diagnostics.append("dataset is empty")
        raise KnowledgeImportError(
            f"Knowledge source contains {rejected} rejected record(s): {'; '.join(diagnostics)}.",
            records_read=len(payload),
            accepted=len(entries),
            rejected=rejected,
            exact_duplicates=duplicates,
            diagnostics=tuple(diagnostics),
        )
    return entries


def load_faq_json(path: Path) -> list[KnowledgeEntry]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeImportError(
            f"Unable to read FAQ JSON {path}: {type(exc).__name__}.",
            records_read=0,
            rejected=1,
            diagnostics=(f"JSON read/parse failed: {type(exc).__name__}",),
        ) from exc
    return _validated_entries(payload, path.name, path)


def load_provenance_json(
    path: Path, entries: list[KnowledgeEntry]
) -> tuple[str, list[ProvenanceRecord]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KnowledgeImportError(
            f"Unable to read provenance JSON {path}: {type(exc).__name__}.",
            records_read=0,
            rejected=1,
            diagnostics=(f"Provenance JSON read/parse failed: {type(exc).__name__}",),
        ) from exc

    if not isinstance(payload, dict) or set(payload) != {
        "dataset_type",
        "dataset_name",
        "records",
    }:
        raise KnowledgeImportError(
            "Provenance document has missing or unknown top-level fields.",
            rejected=1,
            diagnostics=("provenance document schema is invalid",),
        )

    try:
        dataset_type = _provenance_string(payload.get("dataset_type"), "dataset_type")
        dataset_name = _provenance_string(payload.get("dataset_name"), "dataset_name")
    except ValueError as exc:
        raise KnowledgeImportError(
            "Provenance dataset identity is invalid.",
            diagnostics=(str(exc),),
        ) from exc
    try:
        dataset_id = format_dataset_id(dataset_type, dataset_name)
    except ValueError as exc:
        raise KnowledgeImportError(
            "Provenance dataset identity is invalid.",
            diagnostics=(str(exc),),
        ) from exc
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        raise KnowledgeImportError(
            "Provenance records must be a list.",
            rejected=1,
            diagnostics=("provenance records must be a list",),
        )

    entries_by_id = {entry.id: entry for entry in entries}
    seen_ids: set[str] = set()
    records: list[ProvenanceRecord] = []
    diagnostics: list[str] = []
    required_fields = {
        "id",
        "source",
        "source_locator",
        "source_excerpt",
        "provenance_status",
        "owner_review_required",
        "notes",
    }

    for position, item in enumerate(raw_records, start=1):
        try:
            if not isinstance(item, dict) or set(item) != required_fields:
                raise ValueError(f"record {position}: provenance fields are invalid")
            faq_id = _provenance_string(item.get("id"), "id", position)
            if len(faq_id) > MAX_ID_LENGTH or not _ID_PATTERN.fullmatch(faq_id):
                raise ValueError(f"record {position}: provenance id is invalid")
            if faq_id in seen_ids:
                raise ValueError(f"record {position}: duplicate provenance id")
            source = _provenance_string(item.get("source"), "source", position)
            if len(source) > MAX_SOURCE_LENGTH:
                raise ValueError(f"record {position}: provenance source exceeds limit")
            entry = entries_by_id.get(faq_id)
            if entry is None:
                raise ValueError(f"record {position}: provenance FAQ id does not exist")
            if source != entry.source:
                raise ValueError(f"record {position}: provenance source does not match FAQ")

            locator = item.get("source_locator")
            if not isinstance(locator, dict) or set(locator) != {"path", "section"}:
                raise ValueError(f"record {position}: source_locator is invalid")
            locator_path = _provenance_string(locator.get("path"), "source_locator.path", position)
            locator_section = _provenance_string(
                locator.get("section"), "source_locator.section", position
            )
            parsed_path = PurePosixPath(locator_path)
            if (
                parsed_path.is_absolute()
                or "\\" in locator_path
                or not parsed_path.parts
                or any(part in {"", ".", ".."} for part in parsed_path.parts)
            ):
                raise ValueError(f"record {position}: source_locator.path must be relative")

            raw_excerpts = item.get("source_excerpt")
            if not isinstance(raw_excerpts, list) or not raw_excerpts:
                raise ValueError(f"record {position}: source_excerpt must be a non-empty list")
            excerpts: list[dict[str, str]] = []
            for excerpt_number, excerpt in enumerate(raw_excerpts, start=1):
                if not isinstance(excerpt, dict) or set(excerpt) != {"label", "quote"}:
                    raise ValueError(
                        f"record {position}: source_excerpt {excerpt_number} is invalid"
                    )
                excerpts.append(
                    {
                        "label": _provenance_string(
                            excerpt.get("label"), "source_excerpt.label", position
                        ),
                        "quote": _provenance_string(
                            excerpt.get("quote"), "source_excerpt.quote", position
                        ),
                    }
                )

            status = _provenance_string(
                item.get("provenance_status"), "provenance_status", position
            )
            if status not in PROVENANCE_STATUSES:
                raise ValueError(f"record {position}: provenance_status is unsupported")
            owner_review_required = item.get("owner_review_required")
            if type(owner_review_required) is not bool:
                raise ValueError(
                    f"record {position}: owner_review_required must be a boolean"
                )
            notes = item.get("notes")
            if not isinstance(notes, str):
                raise ValueError(f"record {position}: notes must be a string")

            records.append(
                ProvenanceRecord(
                    faq_id=faq_id,
                    source=source,
                    source_locator={"path": locator_path, "section": locator_section},
                    source_excerpt=tuple(excerpts),
                    provenance_status=status,
                    owner_review_required=owner_review_required,
                    dataset_type=dataset_type,
                    dataset_name=dataset_name,
                    notes=notes,
                    dataset_id=dataset_id,
                )
            )
            seen_ids.add(faq_id)
        except ValueError as exc:
            diagnostics.append(str(exc))

    if diagnostics:
        raise KnowledgeImportError(
            "Provenance validation failed.",
            records_read=len(raw_records),
            accepted=len(records),
            rejected=len(raw_records) - len(records),
            diagnostics=tuple(diagnostics),
        )
    if seen_ids != set(entries_by_id):
        missing = sorted(set(entries_by_id) - seen_ids)
        raise KnowledgeImportError(
            "Provenance does not cover every FAQ record.",
            records_read=len(raw_records),
            accepted=len(records),
            rejected=len(entries_by_id) - len(records),
            diagnostics=(f"missing provenance for FAQ id(s): {', '.join(missing)}",),
        )
    return dataset_id, records


def _provenance_string(value: Any, field: str, record_number: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        prefix = f"record {record_number}: " if record_number is not None else ""
        raise ValueError(f"{prefix}{field} must be a non-empty string")
    return value.strip()


def load_txt_documents(directory: Path) -> list[KnowledgeEntry]:
    entries = []
    for path in sorted(directory.glob("*.txt")):
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise KnowledgeImportError(
                f"Unable to read text document {path}: {type(exc).__name__}.",
                rejected=1,
                diagnostics=(f"{path.name}: read failed ({type(exc).__name__})",),
            ) from exc
        if not content:
            continue

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        title = lines[0].removeprefix("#").strip() or path.stem
        body = " ".join(line.removeprefix("#").strip() for line in lines[1:]) or content
        entries.append(KnowledgeEntry(title, body, path.name))
    if not entries:
        return []
    return _validated_entries(
        [
            {"question": entry.question, "answer": entry.answer, "source": entry.source}
            for entry in entries
        ],
        directory.name,
        directory,
    )


def _validate_combined(entries: list[KnowledgeEntry], directory: Path) -> list[KnowledgeEntry]:
    return _validated_entries(
        [
            {
                "id": entry.id or None,
                "question": entry.question,
                "answer": entry.answer,
                "source": entry.source,
            }
            for entry in entries
        ],
        directory.name,
        directory,
    )


def load_knowledge(directory: Path) -> list[KnowledgeEntry]:
    json_path = directory / "faqs.json"
    entries = load_faq_json(json_path) if json_path.exists() else []
    entries.extend(load_txt_documents(directory))
    if not entries:
        raise KnowledgeImportError(
            f"No FAQ JSON or non-empty TXT documents found in {directory}.",
            rejected=1,
            diagnostics=("dataset is empty",),
        )
    return _validate_combined(entries, directory)
