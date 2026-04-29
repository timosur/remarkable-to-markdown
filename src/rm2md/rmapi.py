"""Thin subprocess wrapper around the vendored `rmapi` binary."""
from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Repo root: src/rm2md/rmapi.py -> ../../..
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BIN_DIR = _REPO_ROOT / "bin"


class RmapiError(RuntimeError):
    """Raised when an rmapi invocation fails."""


@dataclass(frozen=True)
class RemoteEntry:
    """A single entry returned by `rmapi ls`."""

    name: str
    is_dir: bool

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        marker = "d" if self.is_dir else "f"
        return f"[{marker}] {self.name}"


def _resolve_rmapi_binary() -> Path:
    """Pick the vendored binary for the current platform, else fall back to PATH."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin" and ("arm" in machine or machine == "aarch64"):
        candidate = _BIN_DIR / "rmapi-darwin-arm64"
    elif system == "linux":
        candidate = _BIN_DIR / "rmapi-linux-arm64"
    else:
        candidate = None

    if candidate and candidate.exists():
        candidate.chmod(0o755)
        return candidate

    on_path = shutil.which("rmapi")
    if on_path:
        return Path(on_path)

    raise RmapiError(
        "No rmapi binary found. Expected vendored binary in "
        f"{_BIN_DIR} or `rmapi` on PATH."
    )


def _run_rmapi(
    args: List[str],
    *,
    cwd: Optional[Path] = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess:
    """Run rmapi with the given args; return the completed process (no raise)."""
    binary = _resolve_rmapi_binary()
    cmd = [str(binary), *args]
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ls(path: str = "/") -> List[RemoteEntry]:
    """List a remote folder. Returns parsed entries.

    rmapi `ls` output format: one entry per line, prefixed with `[d]\\t` or `[f]\\t`.
    """
    result = _run_rmapi(["ls", path])
    if result.returncode != 0:
        raise RmapiError(
            f"rmapi ls {path!r} failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    entries: List[RemoteEntry] = []
    for line in result.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue
        # Expected: "[d]\tName" or "[f]\tName"
        if line.startswith("[d]"):
            entries.append(RemoteEntry(name=line[3:].lstrip("\t ").strip(), is_dir=True))
        elif line.startswith("[f]"):
            entries.append(RemoteEntry(name=line[3:].lstrip("\t ").strip(), is_dir=False))
        else:
            # Unknown line format — keep as a file with the raw name
            entries.append(RemoteEntry(name=line.strip(), is_dir=False))
    return entries


def geta(remote_path: str, dest_dir: Path) -> Path:
    """Download a remote file into ``dest_dir``. Returns the local archive path.

    rmapi writes ``<basename>.zip`` (or ``.rmdoc``) into the working directory.
    Note: rmapi may print 'Failed to generate annotations' but still write the
    file; we treat that as success when the expected file exists.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    basename = Path(remote_path).name or "download"

    result = _run_rmapi(["geta", remote_path], cwd=dest_dir, timeout=300)

    # rmapi typically writes <basename>.zip; some doc types yield .rmdoc.
    candidates = [
        dest_dir / f"{basename}.zip",
        dest_dir / f"{basename}.rmdoc",
        dest_dir / basename,
    ]
    for c in candidates:
        if c.exists() and c.stat().st_size > 0:
            return c

    raise RmapiError(
        f"rmapi geta {remote_path!r} produced no output file in {dest_dir} "
        f"(exit {result.returncode}). stderr: {result.stderr.strip()}"
    )
