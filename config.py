"""Конфигурация приложения из переменных окружения."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта
load_dotenv(Path(__file__).resolve().parent / ".env")


class Config:
    """Базовые настройки Flask-приложения."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-change-in-production"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///app.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    FAQ_API_URL = os.environ.get("FAQ_API_URL", "").strip()
