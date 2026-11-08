import json

import pytest

from app.ingestion import load_faq_json, load_knowledge, load_txt_documents


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
