# SCCS Logging Setup
# Thin wrapper around the stdlib logging module so the rest of the codebase
# can stay on a plain `logger = logging.getLogger(__name__)` pattern.

from __future__ import annotations

import logging
from pathlib import Path

_LOGGER_NAME = "sccs"
_configured = False


def configure_logging(
    *,
    log_file: str | Path | None = None,
    verbose: bool = False,
) -> logging.Logger:
    """Configure the root ``sccs`` logger.

    Idempotent: repeated calls adjust level/handlers without duplicating them.

    Args:
        log_file: Optional path to a log file. When supplied, logs are also
            written to that file at DEBUG level regardless of ``verbose``.
        verbose: If True, console handler emits DEBUG; otherwise WARNING —
            SCCS uses Rich for user-facing output, so the console logger
            stays quiet by default.

    Returns:
        The configured ``sccs`` logger.
    """
    global _configured

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Reset on reconfiguration so we never stack duplicate handlers.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(console_handler)

    # Accept only real path-like values. Tests occasionally pass a MagicMock
    # through here; silently drop anything that isn't a str/Path so we don't
    # create bogus directories named after the mock's repr.
    if log_file and isinstance(log_file, (str, Path)):
        log_path = Path(log_file).expanduser()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(file_handler)
        except OSError as exc:
            # File logging is best-effort; surface via the console handler
            # rather than crashing the CLI when the log path is unwritable.
            logger.warning("Could not open log file %s: %s", log_path, exc)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``sccs`` namespace."""
    if name is None or name == _LOGGER_NAME:
        return logging.getLogger(_LOGGER_NAME)
    if name.startswith(f"{_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_LOGGER_NAME}.{name}")
