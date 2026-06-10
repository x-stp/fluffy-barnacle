#!/usr/bin/env python3
"""
Utility modules for cs-proxy toolkit.

Provides logging, error handling, dependency checking, and configuration
management for the cs-proxy suite of tools.
"""

from .config import Config, create_example_config
from .deps import (
    check_command,
    check_dependencies,
    check_serve_deps,
    check_wireguard_deps,
    get_dependency_install_commands,
)
from .errors import (
    CSProxyError,
    CodespaceError,
    ConfigError,
    DependencyError,
    GitHubAuthError,
    ProxyError,
    SSHTunnelError,
    WireGuardError,
)
from .interaction import eprint, prompt
from .logging import get_logger, log_debug, log_error, log_info, log_warn, setup_logger

__all__ = [
    # Interaction
    "eprint",
    "prompt",
    # Logging
    "setup_logger",
    "get_logger",
    "log_info",
    "log_warn",
    "log_error",
    "log_debug",
    # Errors
    "CSProxyError",
    "DependencyError",
    "GitHubAuthError",
    "CodespaceError",
    "ConfigError",
    "SSHTunnelError",
    "ProxyError",
    "WireGuardError",
    # Dependencies
    "check_command",
    "check_dependencies",
    "check_wireguard_deps",
    "check_serve_deps",
    "get_dependency_install_commands",
    # Configuration
    "Config",
    "create_example_config",
]
