from app.memory import ConversationMemory


def test_conversation_memory_is_session_scoped_and_persistent(tmp_path):
    database = tmp_path / "messages.sqlite3"
    memory = ConversationMemory(database, max_messages=4)
    memory.add_exchange("one", "Привет", "Здравствуйте")
    memory.add_exchange("two", "Другой разговор", "Ответ")
    memory.add_exchange("one", "Когда открыто?", "По будням")

    reopened = ConversationMemory(database)

    assert reopened.get_history("one") == [
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Здравствуйте"},
        {"role": "user", "content": "Когда открыто?"},
        {"role": "assistant", "content": "По будням"},
    ]
    assert reopened.get_history("two") == [
        {"role": "user", "content": "Другой разговор"},
        {"role": "assistant", "content": "Ответ"},
    ]


def test_conversation_memory_caps_old_messages(tmp_path):
    memory = ConversationMemory(tmp_path / "messages.sqlite3", max_messages=2)
    memory.add_exchange("one", "old question", "old answer")
    memory.add_exchange("one", "new question", "new answer")

    assert memory.get_history("one") == [
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "new answer"},
    ]
