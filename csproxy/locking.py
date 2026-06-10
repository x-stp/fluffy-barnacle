"""Cross-platform file locking helpers for csproxy state files."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import portalocker
except ImportError:  # pragma: no cover - exercised by the stdlib fallback tests
    portalocker = None  # type: ignore[assignment]

if os.name == "nt":  # pragma: no cover - Windows-only fallback
    import msvcrt
else:
    import fcntl


@contextmanager
def file_lock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if portalocker is not None:
        try:
            with portalocker.Lock(str(path), mode="a+", timeout=timeout):
                yield
            return
        except portalocker.exceptions.LockException as exc:
            raise TimeoutError(
                f"Could not acquire state lock ({path}). "
                "Another cs-proxy process may be running."
            ) from exc

    with open(path, "a+") as lock_file:
        fd = lock_file.fileno()
        start = time.time()
        while True:
            try:
                if os.name == "nt":  # pragma: no cover - Windows-only fallback
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                else:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() - start > timeout:
                    raise TimeoutError(
                        f"Could not acquire state lock ({path}). "
                        "Another cs-proxy process may be running."
                    )
                time.sleep(0.05)

        try:
            yield
        finally:
            if os.name == "nt":  # pragma: no cover - Windows-only fallback
                lock_file.seek(0)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
