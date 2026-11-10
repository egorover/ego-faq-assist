"""Фабрика приложения Flask."""

import logging

from flask import Flask

from config import Config
from extensions import csrf, db, login_manager
from models.user import User
from routes.admin import admin_bp
from routes.main import main_bp
from utils.logging_config import setup_logging

logger = logging.getLogger(__name__)


def create_app(config_class=Config) -> Flask:
    """Создаёт и настраивает экземпляр Flask."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    setup_logging(app.config["LOG_LEVEL"])

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        seed_admin(app)

    logger.info("Application created")
    return app


def seed_admin(app: Flask) -> None:
    """Создаёт или обновляет учётную запись администратора из конфигурации."""
    username = app.config["ADMIN_USERNAME"]
    password = app.config.get("ADMIN_PASSWORD") or ""

    user = User.query.filter_by(username=username).first()

    if user is None:
        if not password:
            password = "changeme"
            logger.warning(
                "ADMIN_PASSWORD not set; created admin with temporary password 'changeme'"
            )
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        logger.info("Admin user created: username=%s", username)
        return

    if password:
        user.set_password(password)
        db.session.commit()
        logger.info("Admin password updated from environment for username=%s", username)
