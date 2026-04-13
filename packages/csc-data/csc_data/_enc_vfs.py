"""Encrypted VFS helpers for the csc-data package."""

from __future__ import annotations

from pathlib import Path
import json
import os


def find_csc_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or cwd/this file) until `.csc_root` is found."""
    starts = []
    if start is not None:
        start_path = Path(start).resolve()
        starts.append(start_path.parent if start_path.is_file() else start_path)
    env_root = os.environ.get("CSC_ROOT")
    if env_root:
        starts.append(Path(env_root).resolve())
    starts.extend([Path.cwd().resolve(), Path(__file__).resolve()])

    seen: set[Path] = set()
    for origin in starts:
        for candidate in (origin, *origin.parents):
            if candidate in seen:
                continue
            seen.add(candidate)
            if (candidate / ".csc_root").exists():
                return candidate
    raise FileNotFoundError("Could not find CSC_ROOT marker '.csc_root' while walking up from the current checkout.")


class EncryptedVFSStore:
    """Tiny adapter around enc-ext-vfs for CSC log/data usage."""

    def __init__(self, csc_root: Path | None = None):
        self.csc_root = Path(csc_root).resolve() if csc_root else find_csc_root()
        self.storage_root = self.csc_root / "vfs"
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._vfs = None

    def _get_vfs(self):
        if self._vfs is None:
            try:
                from enc_ext_vfs.vfs import VirtualFileSystem
            except Exception as exc:
                raise RuntimeError(
                    "enc-ext-vfs is required for encrypted csc-data storage. "
                    "Install it before using csc_data.Data (for example via the csc-data package dependency plan)."
                ) from exc
            self._vfs = VirtualFileSystem(str(self.storage_root))
        return self._vfs

    @staticmethod
    def _normalize(path: str | Path) -> str:
        """Return the enc pathspec as-is.

        :: is the native CSC encrypted filesystem separator — not a Unix path,
        not a Windows path, just a FAT key.  The FAT is a flat map:
            enc_pathspec  →  block_address (00/11/22/33-44-55-66-77)
        No conversion needed or wanted.  logs::haven-ef6e::relay-ask.log stays
        exactly that.  The block store on disk uses hex addresses; the separator
        in the pathspec is purely for human readability and FAT prefix lookups.
        """
        return str(path).strip()

    def exists(self, path: str | Path) -> bool:
        return self._get_vfs().exists(self._normalize(path))

    def read_bytes(self, path: str | Path) -> bytes:
        vpath = self._normalize(path)
        if not self.exists(vpath):
            return b""
        return self._get_vfs().read(vpath, requester="root")

    def write_bytes(self, path: str | Path, data: bytes, mime_type: str = "application/octet-stream") -> None:
        vpath = self._normalize(path)
        vfs = self._get_vfs()
        if vfs.exists(vpath):
            vfs.write(vpath, data)
        else:
            vfs.create(vpath, data, mime_type=mime_type)

    def read_text(self, path: str | Path) -> str:
        return self.read_bytes(path).decode("utf-8") if self.exists(path) else ""

    def write_text(self, path: str | Path, data: str) -> None:
        self.write_bytes(path, data.encode("utf-8"), mime_type="text/plain")

    def append_text(self, path: str | Path, text: str) -> None:
        existing = self.read_text(path)
        self.write_text(path, existing + text)

    def read_json(self, path: str | Path) -> dict:
        raw = self.read_text(path)
        return json.loads(raw) if raw.strip() else {}

    def write_json(self, path: str | Path, data: dict) -> None:
        self.write_text(path, json.dumps(data, indent=2))


def get_vfs_store(csc_root: Path | None = None) -> EncryptedVFSStore:
    return EncryptedVFSStore(csc_root=csc_root)
