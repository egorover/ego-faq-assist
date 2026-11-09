import json

import pytest

from app.ingestion import (
    MAX_ANSWER_LENGTH,
    MAX_ID_LENGTH,
    MAX_QUESTION_LENGTH,
    MAX_SOURCE_LENGTH,
    KnowledgeImportError,
    format_dataset_id,
    load_faq_json,
    load_knowledge,
    load_txt_documents,
)


def test_load_faq_and_text_documents(tmp_path):
    (tmp_path / "faqs.json").write_text(
        json.dumps([{"question": "  Как   записаться? ", "answer": " Напишите нам. "}]),
        encoding="utf-8",
    )
    (tmp_path / "rules.txt").write_text("# Правила\n\nУчастие бесплатное.\n", encoding="utf-8")

    entries = load_knowledge(tmp_path)

    assert len(entries) == 2
    assert entries[0].question == "Как записаться?"
    assert entries[0].answer == "Напишите нам."
    assert entries[1].question == "Правила"
    assert entries[1].answer == "Участие бесплатное."
    assert entries[1].source == "rules.txt"


def test_reject_invalid_faq_entry(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('[{"question":"Q","answer":""}]', encoding="utf-8")

    with pytest.raises(ValueError, match="answer"):
        load_faq_json(path)


def test_empty_txt_files_are_skipped(tmp_path):
    (tmp_path / "blank.txt").write_text(" \n ", encoding="utf-8")

    assert load_txt_documents(tmp_path) == []


@pytest.mark.parametrize(
    "payload",
    [
        [{"question": "Q", "answer": "A"}],
        {"faqs": [{"question": "Q", "answer": "A"}]},
    ],
)
def test_json_formats_generate_deterministic_id_and_default_source(tmp_path, payload):
    path = tmp_path / "faqs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    entry = load_faq_json(path)[0]

    assert entry.id.startswith("faq-")
    assert len(entry.id) == 28
    assert entry.source == "faqs.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_faq_json(path)[0].id == entry.id


def test_optional_id_and_source_are_preserved_and_normalized(tmp_path):
    path = tmp_path / "faqs.json"
    path.write_text(
        json.dumps(
            {
                "faqs": [
                    {
                        "id": " stable-id ",
                        "question": "  A   question ",
                        "answer": "An   answer",
                        "source": " policy   v1 ",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    entry = load_faq_json(path)[0]

    assert (entry.id, entry.question, entry.answer, entry.source) == (
        "stable-id",
        "A question",
        "An answer",
        "policy v1",
    )


def test_malformed_json_reports_parse_failure(tmp_path):
    path = tmp_path / "faqs.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(KnowledgeImportError, match="JSONDecodeError") as error:
        load_faq_json(path)

    assert error.value.rejected == 1


@pytest.mark.parametrize(
    "record, expected_field",
    [
        ({"answer": "A"}, "question"),
        ({"question": "Q"}, "answer"),
        ({"question": "", "answer": "A"}, "question"),
        ({"question": "Q", "answer": ""}, "answer"),
        ({"question": "Q", "answer": "A", "source": ""}, "source"),
        ({"question": "Q", "answer": "A", "id": ""}, "id"),
    ],
)
def test_missing_and_empty_fields_are_rejected(tmp_path, record, expected_field):
    path = tmp_path / "faqs.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(KnowledgeImportError, match=expected_field):
        load_faq_json(path)


@pytest.mark.parametrize(
    "field, maximum",
    [
        ("question", MAX_QUESTION_LENGTH),
        ("answer", MAX_ANSWER_LENGTH),
        ("source", MAX_SOURCE_LENGTH),
        ("id", MAX_ID_LENGTH),
    ],
)
def test_over_limit_fields_are_rejected(tmp_path, field, maximum):
    record = {"question": "Q", "answer": "A", field: "x" * (maximum + 1)}
    path = tmp_path / "faqs.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(KnowledgeImportError, match="exceeds"):
        load_faq_json(path)


def test_empty_dataset_is_rejected(tmp_path):
    path = tmp_path / "faqs.json"
    path.write_text('{"faqs": []}', encoding="utf-8")

    with pytest.raises(KnowledgeImportError, match="empty"):
        load_faq_json(path)


def test_exact_duplicate_question_answer_is_rejected_case_insensitively(tmp_path):
    path = tmp_path / "faqs.json"
    path.write_text(
        json.dumps(
            [
                {"question": "A question", "answer": "An answer", "source": "one"},
                {"question": " a   QUESTION ", "answer": "AN ANSWER", "source": "two"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeImportError, match="exact duplicate") as error:
        load_faq_json(path)

    assert error.value.records_read == 2
    assert error.value.accepted == 1
    assert error.value.rejected == 1
    assert error.value.exact_duplicates == 1


def test_duplicate_explicit_ids_are_rejected(tmp_path):
    path = tmp_path / "faqs.json"
    path.write_text(
        json.dumps(
            [
                {"id": "same-id", "question": "Question one", "answer": "Answer one"},
                {"id": "same-id", "question": "Question two", "answer": "Answer two"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(KnowledgeImportError, match="duplicate id"):
        load_faq_json(path)


@pytest.mark.parametrize(
    ("dataset_type", "dataset_name"),
    [
        ("pilot:other", "dataset"),
        ("pilot", "dataset:name"),
        ("pilot type", "dataset"),
        ("pilot", "dataset/name"),
    ],
)
def test_dataset_identity_rejects_ambiguous_or_invalid_components(
    dataset_type, dataset_name
):
    with pytest.raises(ValueError, match="dataset_type and dataset_name"):
        format_dataset_id(dataset_type, dataset_name)


def test_dataset_identity_format_remains_stable():
    assert format_dataset_id("pilot", "ego_promptfolio") == "pilot:ego_promptfolio"
