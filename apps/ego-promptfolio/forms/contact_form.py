"""Форма обратной связи."""

from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Regexp


class ContactForm(FlaskForm):
    """Поля: имя, email, телефон, тема сообщения."""

    name = StringField(
        "Имя",
        validators=[
            DataRequired(message="Укажите имя."),
            Length(min=2, max=100, message="Имя: от 2 до 100 символов."),
        ],
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Укажите email."),
            Email(message="Некорректный email."),
        ],
    )
    phone = StringField(
        "Телефон",
        validators=[
            DataRequired(message="Укажите телефон."),
            Regexp(
                r"^\+?[\d\s\-()]{7,20}$",
                message="Некорректный формат телефона.",
            ),
        ],
    )
    subject = TextAreaField(
        "Тема сообщения",
        validators=[
            DataRequired(message="Укажите тему сообщения."),
            Length(min=5, max=200, message="Тема: от 5 до 200 символов."),
        ],
    )
