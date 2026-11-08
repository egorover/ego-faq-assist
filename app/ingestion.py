import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class KnowledgeEntry:
    question: str
    answer: str
    source: str

    @property
    def embedding_text(self) -> str:
        return f"{self.question}\n{self.answer}"


def _normalize(value: Any, field: str, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: each FAQ entry must have a non-empty '{field}'.")
    return " ".join(value.split())


def load_faq_json(path: Path) -> list[KnowledgeEntry]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read FAQ JSON {path}: {exc}") from exc

    if isinstance(payload, dict):
        payload = payload.get("faqs")
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a list of FAQ objects.")

    entries = []
    for position, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: FAQ item {position} must be an object.")
        entries.append(
            KnowledgeEntry(
                question=_normalize(item.get("question"), "question", str(path)),
                answer=_normalize(item.get("answer"), "answer", str(path)),
                source=_normalize(item.get("source", path.name), "source", str(path)),
            )
        )
    return entries


def load_txt_documents(directory: Path) -> list[KnowledgeEntry]:
    entries = []
    for path in sorted(directory.glob("*.txt")):
        try:
            content = path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            raise ValueError(f"Unable to read text document {path}: {exc}") from exc
        if not content:
            continue

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        title = lines[0].removeprefix("#").strip() or path.stem
        body = " ".join(line.removeprefix("#").strip() for line in lines[1:]) or content
        entries.append(
            KnowledgeEntry(
                question=_normalize(title, "question", path.name),
                answer=_normalize(body, "answer", path.name),
                source=path.name,
            )
        )
    return entries


def load_knowledge(directory: Path) -> list[KnowledgeEntry]:
    json_path = directory / "faqs.json"
    entries = load_faq_json(json_path) if json_path.exists() else []
    entries.extend(load_txt_documents(directory))
    if not entries:
        raise ValueError(f"No FAQ JSON or non-empty TXT documents found in {directory}.")
    return entries

