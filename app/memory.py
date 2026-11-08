import sqlite3
from pathlib import Path


class ConversationMemory:
    def __init__(self, database_path: Path, max_messages: int = 40):
        self.database_path = database_path
        self.max_messages = max_messages
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10)

    def get_history(self, session_id: str, limit: int = 12) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": role, "content": content} for role, content in reversed(rows)]

    def add_exchange(self, session_id: str, user_message: str, assistant_message: str) -> None:
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (
                    (session_id, "user", user_message),
                    (session_id, "assistant", assistant_message),
                ),
            )
            connection.execute(
                """DELETE FROM messages WHERE session_id = ? AND id NOT IN (
                    SELECT id FROM messages WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                )""",
                (session_id, session_id, self.max_messages),
            )

