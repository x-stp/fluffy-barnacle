#!/usr/bin/env python3
"""
Logging utilities for cs-proxy toolkit.

Provides colored, leveled logging with file output support, replacing the
Bash logging functions from lib/common.sh.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from colorama import Fore, Style, init

    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colored output for different log levels."""

    # Color mappings for log levels
    if COLORAMA_AVAILABLE:
        COLORS = {
            logging.DEBUG: Fore.CYAN,
            logging.INFO: Fore.GREEN,
            logging.WARNING: Fore.YELLOW,
            logging.ERROR: Fore.RED,
            logging.CRITICAL: Fore.RED + Style.BRIGHT,
        }
    else:
        COLORS = {}

    # Level name display format
    LEVEL_NAMES = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARN",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        # Get color for this level
        color = self.COLORS.get(record.levelno, "")
        reset = Style.RESET_ALL if COLORAMA_AVAILABLE else ""

        # Get custom level name
        level_name = self.LEVEL_NAMES.get(record.levelno, record.levelname)

        # Format: [LEVEL] message
        if color:
            record.levelname = f"{color}[{level_name}]{reset}"
        else:
            record.levelname = f"[{level_name}]"

        return super().format(record)


class FileFormatter(logging.Formatter):
    """Formatter for file output without color codes."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for file output with timestamp."""
        # Add timestamp for file logs
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record.timestamp = timestamp
        record.levelname = f"[{record.levelname}]"
        return super().format(record)


def setup_logger(
    name: str = "csproxy", verbose: bool = False, log_file: Optional[Path] = None
) -> logging.Logger:
    """
    Set up and configure logger with colored console output and optional file logging.

    Args:
        name: Logger name (default: 'csproxy')
        verbose: Enable DEBUG level logging (default: False)
        log_file: Optional path to log file for persistent logging

    Returns:
        Configured logger instance

    Example:
        >>> logger = setup_logger(verbose=True)
        >>> logger.info("Proxy started")
        >>> logger.error("Connection failed")
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Set base level
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_formatter = ColoredFormatter("%(levelname)s %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler if log file specified
    if log_file:
        try:
            # Ensure log directory exists
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file, mode="a")
            file_handler.setLevel(logging.DEBUG)  # Always log everything to file
            file_formatter = FileFormatter("[%(timestamp)s] %(levelname)s %(message)s")
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            # If we can't write to log file, just warn but continue
            logger.warning(f"Could not open log file {log_file}: {e}")

    return logger


def get_logger(name: str = "csproxy") -> logging.Logger:
    """
    Get existing logger instance.

    Args:
        name: Logger name (default: 'csproxy')

    Returns:
        Logger instance (creates default if not exists)
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Return default logger if not yet configured
        return setup_logger(name)
    return logger


# Convenience function for quick logging setup
def log_info(message: str) -> None:
    """Quick INFO log."""
    get_logger().info(message)


def log_warn(message: str) -> None:
    """Quick WARNING log."""
    get_logger().warning(message)


def log_error(message: str) -> None:
    """Quick ERROR log."""
    get_logger().error(message)


def log_debug(message: str) -> None:
    """Quick DEBUG log."""
    get_logger().debug(message)
