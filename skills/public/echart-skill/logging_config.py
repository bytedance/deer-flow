import logging
import sys
from pathlib import Path
from typing import Any

import structlog


def configure_logging(
    log_file: str = "logs/echart-skill.log",
    level: int = logging.INFO,
) -> None:
    """
    Configure structlog for the application.

    Args:
        log_file: Path to log file
        level: Minimum log level
    """
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Reset root logger to allow reconfiguration
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    # Add file handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(file_handler)

    # Configure structlog processors
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a configured structlog logger.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class LogOperation:
    """Context manager for logging operation start/end."""

    def __init__(self, logger: structlog.stdlib.BoundLogger, operation: str, **context: Any):
        self.logger = logger
        self.operation = operation
        self.context = context

    def __enter__(self) -> "LogOperation":
        self.logger.info(f"开始{self.operation}", **self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is None:
            self.logger.info(f"完成{self.operation}", **self.context)
        else:
            self.logger.error(
                f"{self.operation}失败",
                error=str(exc_val),
                error_type=exc_type.__name__,
                **self.context
            )
