"""Заявки из формы обратной связи."""

from datetime import datetime, timezone

from extensions import db


class ContactSubmission(db.Model):
    """Обращение пользователя через форму контактов."""

    __tablename__ = "contact_submissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    is_read = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<ContactSubmission {self.id}>"
