#!/usr/bin/env python3
"""
Shared subprocess runner for cs-proxy.

Centralizes command execution so CLI features can share timeout handling,
environment injection, logging, and dry-run behavior.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .utils.logging import get_logger

_DEFAULT_TIMEOUT = object()


@dataclass
class CommandRunner:
    """Small wrapper around subprocess.run with cs-proxy defaults."""

    default_timeout: Optional[int] = 30
    dry_run: bool = False
    base_env: Optional[Mapping[str, str]] = None
    redacted_values: Sequence[str] = field(default_factory=tuple)

    @staticmethod
    def _looks_sensitive_env_key(key: str) -> bool:
        upper = key.upper()
        return any(
            marker in upper
            for marker in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY", "API_KEY", "AUTH")
        )

    def _redact_text(self, value: str) -> str:
        shown = value
        for secret in (v for v in self.redacted_values if v):
            shown = shown.replace(secret, "***")
        return shown

    def _merged_env(self, env: Optional[Mapping[str, str]] = None) -> Optional[dict[str, str]]:
        if self.base_env is None and env is None:
            return None
        merged = dict(os.environ)
        if self.base_env:
            merged.update(self.base_env)
        if env:
            merged.update(env)
        return merged

    def _display_cmd(self, cmd: Sequence[str]) -> str:
        parts = []
        redacted = {v for v in self.redacted_values if v}
        for part in cmd:
            shown = str(part)
            for value in redacted:
                shown = shown.replace(value, "***")
            parts.append(shown)
        return " ".join(parts)

    def _display_env(self, env: Optional[Mapping[str, str]]) -> str:
        if not env:
            return ""
        shown = []
        for key in sorted(env):
            value = env[key]
            if self._looks_sensitive_env_key(key):
                shown.append(f"{key}=***")
            else:
                shown.append(f"{key}={self._redact_text(str(value))}")
        return " ".join(shown)

    def run(
        self,
        cmd: Sequence[str],
        *,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
        timeout: object = _DEFAULT_TIMEOUT,
        env: Optional[Mapping[str, str]] = None,
        input=None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Run a command with consistent defaults."""
        logger = get_logger()
        merged_env = self._merged_env(env)
        logger.debug(f"Running: {self._display_cmd(cmd)}")
        if env:
            logger.debug(f"With env: {self._display_env(env)}")

        if self.dry_run:
            return subprocess.CompletedProcess(list(cmd), 0, stdout="", stderr="")

        return subprocess.run(
            list(cmd),
            check=check,
            capture_output=capture_output,
            text=text,
            timeout=self.default_timeout if timeout is _DEFAULT_TIMEOUT else timeout,
            env=merged_env,
            input=input,
            **kwargs,
        )

    def gh(self, args: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a GitHub CLI command."""
        return self.run(["gh", *args], **kwargs)
