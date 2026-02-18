#!/usr/bin/env python3
"""
Custom exceptions for cs-proxy toolkit.

Provides a hierarchy of exceptions for better error handling than the
Bash die() function from lib/common.sh.
"""


class CSProxyError(Exception):
    """Base exception for all cs-proxy errors."""

    def __init__(self, message: str, exit_code: int = 1):
        """
        Initialize exception.

        Args:
            message: Error message
            exit_code: Exit code to use when this error causes program termination
        """
        super().__init__(message)
        self.exit_code = exit_code


class DependencyError(CSProxyError):
    """Raised when required dependency is missing."""

    def __init__(self, missing_deps: list[str]):
        """
        Initialize dependency error.

        Args:
            missing_deps: List of missing dependency names
        """
        deps_str = ', '.join(missing_deps)
        message = f"Missing dependencies: {deps_str}. Please install them first."
        super().__init__(message, exit_code=1)
        self.missing_deps = missing_deps


class GitHubAuthError(CSProxyError):
    """Raised when GitHub authentication fails."""

    def __init__(self, message: str = "GitHub authentication required"):
        """
        Initialize GitHub auth error.

        Args:
            message: Custom error message
        """
        super().__init__(message, exit_code=1)


class CodespaceError(CSProxyError):
    """Raised when Codespace operations fail."""

    def __init__(self, message: str, codespace_name: str = None):
        """
        Initialize Codespace error.

        Args:
            message: Error message
            codespace_name: Name of the Codespace (if applicable)
        """
        if codespace_name:
            message = f"Codespace '{codespace_name}': {message}"
        super().__init__(message, exit_code=1)
        self.codespace_name = codespace_name


class ConfigError(CSProxyError):
    """Raised when configuration is invalid or cannot be loaded."""

    def __init__(self, message: str, config_file: str = None):
        """
        Initialize config error.

        Args:
            message: Error message
            config_file: Path to config file (if applicable)
        """
        if config_file:
            message = f"Config file '{config_file}': {message}"
        super().__init__(message, exit_code=1)
        self.config_file = config_file


class SSHTunnelError(CSProxyError):
    """Raised when SSH tunnel operations fail."""

    def __init__(self, message: str):
        """
        Initialize SSH tunnel error.

        Args:
            message: Error message
        """
        super().__init__(message, exit_code=1)


class ProxyError(CSProxyError):
    """Raised when proxy operations fail."""

    def __init__(self, message: str, port: int = None):
        """
        Initialize proxy error.

        Args:
            message: Error message
            port: Port number (if applicable)
        """
        if port:
            message = f"Port {port}: {message}"
        super().__init__(message, exit_code=1)
        self.port = port


class WireGuardError(CSProxyError):
    """Raised when WireGuard operations fail."""

    def __init__(self, message: str):
        """
        Initialize WireGuard error.

        Args:
            message: Error message
        """
        super().__init__(message, exit_code=1)
