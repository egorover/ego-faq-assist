"""Настройка логирования для приложения."""

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Конфигурирует корневой логгер с выводом в stdout."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
