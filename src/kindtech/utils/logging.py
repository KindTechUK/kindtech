"""Logging utilities for consistent logging across the kindtech package."""

import logging

# Track if we've configured the root logger
_ROOT_LOGGER_CONFIGURED = False


def get_logger(name: str | None = None) -> logging.Logger:
    """
    Get a logger with consistent formatting for the kindtech package.

    This function ensures all loggers in the package use the same format:
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    If the root logger already has handlers (e.g., from basicConfig), child
    loggers will propagate to it. Otherwise, a handler is added to the root
    logger to avoid duplicate messages.

    Args:
        name: Logger name. If None, uses the calling module's name.

    Returns:
        A configured logger instance.

    Examples:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing data")
    """
    global _ROOT_LOGGER_CONFIGURED

    root_logger = logging.getLogger()

    # Configure root logger once if it doesn't have handlers
    if not _ROOT_LOGGER_CONFIGURED and not root_logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
        _ROOT_LOGGER_CONFIGURED = True

    # Get the requested logger (will propagate to root logger)
    logger = logging.getLogger(name or __name__)
    logger.setLevel(logging.INFO)

    return logger
