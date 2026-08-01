import logging

from app.core.settings import Settings

DEFAULT_LOG_FORMAT = "%(levelname)s:     %(message)s"


def configure_logging(settings: Settings) -> None:
    app_level = logging.getLevelName(settings.log_level)
    sqlalchemy_level = logging.getLevelName(settings.sqlalchemy_log_level)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=app_level,
            format=DEFAULT_LOG_FORMAT,
        )
    root_logger.setLevel(app_level)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "app",
    ):
        logging.getLogger(logger_name).setLevel(app_level)

    for logger_name in (
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
    ):
        logging.getLogger(logger_name).setLevel(sqlalchemy_level)
