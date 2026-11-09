"""Форма входа в админ-панель."""

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    """Логин и пароль администратора."""

    username = StringField(
        "Логин",
        validators=[
            DataRequired(message="Введите логин."),
            Length(max=80),
        ],
    )
    password = PasswordField(
        "Пароль",
        validators=[DataRequired(message="Введите пароль.")],
    )
    remember = BooleanField("Запомнить меня")
