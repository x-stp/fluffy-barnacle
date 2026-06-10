#!/usr/bin/env python3
"""
Dependency checking utilities for cs-proxy toolkit.

Provides functions to verify required external commands are available,
replacing the check_deps() function from lib/common.sh.
"""

import shutil
from typing import List, Optional

from .errors import DependencyError
from .logging import get_logger


def check_command(command: str) -> bool:
    """
    Check if a command is available in PATH.

    Args:
        command: Command name to check

    Returns:
        True if command is available, False otherwise

    Example:
        >>> check_command('gh')
        True
        >>> check_command('nonexistent')
        False
    """
    return shutil.which(command) is not None


def check_dependencies(
    required: Optional[List[str]] = None,
    optional: Optional[List[str]] = None,
    raise_on_missing: bool = True,
) -> tuple[list[str], list[str]]:
    """
    Check for required and optional dependencies.

    Args:
        required: List of required command names (default: ['gh', 'ssh', 'curl'])
        optional: List of optional command names (default: [])
        raise_on_missing: Raise DependencyError if required deps missing (default: True)

    Returns:
        Tuple of (missing_required, missing_optional)

    Raises:
        DependencyError: If required dependencies are missing and raise_on_missing=True

    Example:
        >>> check_dependencies(['gh', 'ssh'], ['jq'])
        ([], ['jq'])  # gh and ssh found, jq not found
    """
    logger = get_logger()

    # Default required dependencies
    if required is None:
        required = ["gh", "ssh", "curl"]

    if optional is None:
        optional = []

    # Check required dependencies
    missing_required = []
    for cmd in required:
        if not check_command(cmd):
            missing_required.append(cmd)
        else:
            logger.debug(f"Found required dependency: {cmd}")

    # Check optional dependencies
    missing_optional = []
    for cmd in optional:
        if not check_command(cmd):
            missing_optional.append(cmd)
            logger.debug(f"Optional dependency not found: {cmd}")
        else:
            logger.debug(f"Found optional dependency: {cmd}")

    # Handle missing required dependencies
    if missing_required:
        logger.error(f"Missing required dependencies: {', '.join(missing_required)}")

        # Provide installation hints
        if "gh" in missing_required:
            logger.info("Install GitHub CLI from: https://cli.github.com/")

        if raise_on_missing:
            raise DependencyError(missing_required)

    if not missing_required and not missing_optional:
        logger.debug("All dependencies found")

    return missing_required, missing_optional


def check_wireguard_deps() -> bool:
    """
    Check if WireGuard dependencies are available.

    Returns:
        True if all WireGuard dependencies are available

    Note:
        WireGuard requires: wg, wg-quick, socat, ip (iproute2)
    """
    logger = get_logger()
    wg_deps = ["wg", "wg-quick", "socat", "ip"]

    missing = [cmd for cmd in wg_deps if not check_command(cmd)]

    if missing:
        logger.warning(f"WireGuard dependencies missing: {', '.join(missing)}")
        logger.info("Install with: sudo apt install wireguard-tools socat iproute2")
        return False

    logger.debug("All WireGuard dependencies found")
    return True


def check_serve_deps() -> bool:
    """
    Check if file serving dependencies are available.

    Returns:
        True if Python's http.server is available (always True for Python 3.x)

    Note:
        Python 3.x includes http.server in the standard library, so this
        always returns True but is kept for consistency with other dep checks.
    """
    # Python 3 always has http.server
    return True


def get_dependency_install_commands() -> dict[str, str]:
    """
    Get installation commands for common dependencies by platform.

    Returns:
        Dictionary mapping dependency names to installation commands

    Example:
        >>> cmds = get_dependency_install_commands()
        >>> print(cmds['gh'])
        'https://cli.github.com/manual/installation'
    """
    return {
        "gh": "https://cli.github.com/manual/installation",
        "ssh": "sudo apt install openssh-client  # Debian/Ubuntu",
        "curl": "sudo apt install curl",
        "jq": "sudo apt install jq",
        "socat": "sudo apt install socat",
        "wireguard": "sudo apt install wireguard-tools",
        "iproute2": "sudo apt install iproute2",
        "proxychains4": "sudo apt install proxychains4",
        "tinyproxy": "sudo apt install tinyproxy",
    }
