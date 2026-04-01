"""
wo_watcher.py — Filesystem watcher for ops/wo/.

Monitors ops/wo/ for any change and pushes changed files to the FTP master
(fahu), which replicates to all registered slave nodes.

Detection strategy (priority order):
  1. inotify (Linux kernel) via inotify_simple if available
  2. watchdog library (cross-platform)
  3. Pure polling fallback — stat() every poll_interval_s seconds

Debounce: batches changes within a 500ms window before pushing.
"""

import ftplib
import hashlib
import logging
import os
import platform
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filelist hash helpers
# ---------------------------------------------------------------------------

def compute_filelist_hash(wo_dir: Path) -> str:
    """Return SHA-256 of sorted 'relpath:size:mtime' entries under wo_dir."""
    entries = []
    for root, dirs, files in os.walk(str(wo_dir)):
        dirs.sort()
        for fname in sorted(files):
            full = Path(root) / fname
            try:
                st = full.stat()
                rel = full.relative_to(wo_dir).as_posix()
                entries.append(f"{rel}:{st.st_size}:{st.st_mtime:.3f}")
            except OSError:
                pass
    digest = hashlib.sha256("\n".join(entries).encode()).hexdigest()
    return digest


# ---------------------------------------------------------------------------
# FTP push helpers
# ---------------------------------------------------------------------------

def _ftp_push_file(ftp: ftplib.FTP_TLS, local_path: Path, remote_path: str) -> None:
    """Upload local_path to remote_path on the FTP connection."""
    # Ensure remote directory exists
    parts = remote_path.rsplit("/", 1)
    if len(parts) == 2:
        remote_dir = parts[0]
        try:
            ftp.mkd(remote_dir)
        except ftplib.error_perm:
            pass  # directory already exists

    with open(local_path, "rb") as fh:
        ftp.storbinary(f"STOR {remote_path}", fh)


def _ftp_delete_file(ftp: ftplib.FTP_TLS, remote_path: str) -> None:
    """Delete remote_path on the FTP connection."""
    try:
        ftp.delete(remote_path)
    except ftplib.error_perm as exc:
        log.warning("DELE %s: %s", remote_path, exc)


def _connect_ftp(host: str, port: int, user: str, password: str) -> ftplib.FTP_TLS:
    """Open an authenticated FTP_TLS connection."""
    ftp = ftplib.FTP_TLS()
    ftp.connect(host, port, timeout=30)
    ftp.auth()
    ftp.login(user, password)
    ftp.prot_p()
    return ftp


# ---------------------------------------------------------------------------
# Core watcher
# ---------------------------------------------------------------------------

class WoWatcher:
    """Monitors ops/wo/ and pushes changes through the FTP master.

    Args:
        wo_dir: Absolute path to the ops/wo/ directory to watch.
        ftp_master_host: Hostname of the FTP master (fahu).
        ftp_master_port: Control port (default 9521).
        ftp_user: FTP username for authentication.
        ftp_password: FTP password / credential.
        debounce_ms: Milliseconds to batch rapid changes (default 500).
        poll_interval_s: Polling interval in seconds for fallback (default 5).
        on_change_hook: Optional extra callback called after each push.
    """

    def __init__(
        self,
        wo_dir: str,
        ftp_master_host: str,
        ftp_master_port: int = 9521,
        ftp_user: str = "csc-node",
        ftp_password: str = "",
        debounce_ms: int = 500,
        poll_interval_s: int = 5,
        on_change_hook: Optional[Callable[[str], None]] = None,
    ):
        self.wo_dir = Path(wo_dir).resolve()
        self.ftp_master_host = ftp_master_host
        self.ftp_master_port = ftp_master_port
        self.ftp_user = ftp_user
        self.ftp_password = ftp_password
        self.debounce_s = debounce_ms / 1000.0
        self.poll_interval_s = poll_interval_s
        self.on_change_hook = on_change_hook

        self._stop_event = threading.Event()
        self._pending_changes: Set[str] = set()  # relative paths
        self._pending_deletions: Set[str] = set()
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # Snapshot used by polling fallback: {rel_path: (size, mtime)}
        self._snapshot: Dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching. Blocks until stop() is called."""
        log.info("WoWatcher: starting on %s", self.wo_dir)
        system = platform.system()

        if system == "Linux":
            self._start_inotify()
        elif system == "Darwin":
            self._start_watchdog_or_poll()
        else:
            # Windows + anything else — polling via threading.Timer loop
            self._start_poll_loop()

    def stop(self) -> None:
        """Signal the watcher to stop."""
        self._stop_event.set()

    def on_change(self, changed_path: str) -> None:
        """Called when any file in ops/wo/ changes.  Schedules debounced push."""
        with self._lock:
            self._pending_changes.add(changed_path)
            self._reschedule_debounce()

    def on_delete(self, deleted_path: str) -> None:
        """Called when a file is deleted from ops/wo/."""
        with self._lock:
            self._pending_deletions.add(deleted_path)
            self._reschedule_debounce()

    # ------------------------------------------------------------------
    # Internal: debounce + push
    # ------------------------------------------------------------------

    def _reschedule_debounce(self) -> None:
        """(Re-)schedule the debounce timer.  Must be called with self._lock held."""
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
        self._debounce_timer = threading.Timer(self.debounce_s, self._flush)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _flush(self) -> None:
        """Push accumulated changes to the FTP master."""
        with self._lock:
            changes = set(self._pending_changes)
            deletions = set(self._pending_deletions)
            self._pending_changes.clear()
            self._pending_deletions.clear()
            self._debounce_timer = None

        if not changes and not deletions:
            return

        log.info(
            "WoWatcher: flushing %d changes, %d deletions",
            len(changes),
            len(deletions),
        )
        try:
            ftp = _connect_ftp(
                self.ftp_master_host,
                self.ftp_master_port,
                self.ftp_user,
                self.ftp_password,
            )
            try:
                for rel_path in sorted(changes):
                    local = self.wo_dir / rel_path
                    if local.exists():
                        remote = f"wo/{rel_path}"
                        log.debug("STOR %s", remote)
                        _ftp_push_file(ftp, local, remote)
                    else:
                        # File disappeared between detection and flush — treat as deletion
                        deletions.add(rel_path)

                for rel_path in sorted(deletions):
                    remote = f"wo/{rel_path}"
                    log.debug("DELE %s", remote)
                    _ftp_delete_file(ftp, remote)

                # Update filelist hash on master
                filelist_hash = compute_filelist_hash(self.wo_dir)
                hash_bytes = filelist_hash.encode()
                import io
                ftp.storbinary("STOR wo/.filelist.hash", io.BytesIO(hash_bytes))
                log.info("WoWatcher: pushed filelist hash %s", filelist_hash[:12])

            finally:
                try:
                    ftp.quit()
                except Exception:
                    if hasattr(self, 'log'):
                        self.log('Ignored exception', level='DEBUG')
        except Exception as exc:
            log.error("WoWatcher: FTP push failed: %s", exc)

        # Optional extra hook (e.g. for testing)
        all_changed = changes | deletions
        if self.on_change_hook:
            for path in all_changed:
                self.on_change_hook(path)

    # ------------------------------------------------------------------
    # Internal: inotify (Linux)
    # ------------------------------------------------------------------

    def _start_inotify(self) -> None:
        """Use inotify_simple if available, else fall back to poll."""
        try:
            import inotify_simple  # type: ignore
            self._run_inotify_simple(inotify_simple)
        except ImportError:
            log.info("WoWatcher: inotify_simple not found, falling back to polling")
            self._start_poll_loop()

    def _run_inotify_simple(self, inotify_simple) -> None:
        """Block on inotify events until stop() is called."""
        IN_FLAGS = (
            inotify_simple.flags.CREATE
            | inotify_simple.flags.CLOSE_WRITE
            | inotify_simple.flags.MOVED_TO
            | inotify_simple.flags.MOVED_FROM
            | inotify_simple.flags.DELETE
        )

        inotify = inotify_simple.INotify()
        # Watch root and all subdirectories
        wd_to_dir: Dict[int, Path] = {}

        def add_watches(directory: Path) -> None:
            try:
                wd = inotify.add_watch(str(directory), IN_FLAGS)
                wd_to_dir[wd] = directory
            except OSError as e:
                log.warning("WoWatcher: could not watch %s: %s", directory, e)
            for sub in directory.iterdir():
                if sub.is_dir():
                    add_watches(sub)

        add_watches(self.wo_dir)
        log.info("WoWatcher: inotify watching %d dirs", len(wd_to_dir))

        DELETE_FLAGS = (
            inotify_simple.flags.DELETE
            | inotify_simple.flags.MOVED_FROM
        )

        while not self._stop_event.is_set():
            events = inotify.read(timeout=1000)  # 1 s timeout to check stop_event
            for event in events:
                directory = wd_to_dir.get(event.wd)
                if directory is None:
                    continue
                full = directory / event.name
                try:
                    rel = str(full.relative_to(self.wo_dir))
                except ValueError:
                    rel = str(full)

                # Watch new subdirectories
                if (
                    event.mask & inotify_simple.flags.CREATE
                    and full.is_dir()
                ):
                    add_watches(full)
                    continue

                if event.name.startswith(".") and event.name != ".filelist.hash":
                    continue  # skip hidden temp files

                if event.mask & DELETE_FLAGS:
                    self.on_delete(rel)
                else:
                    self.on_change(rel)

    # ------------------------------------------------------------------
    # Internal: watchdog (macOS / cross-platform)
    # ------------------------------------------------------------------

    def _start_watchdog_or_poll(self) -> None:
        """Use watchdog if available, otherwise fall back to polling."""
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler  # type: ignore

            watcher_self = self

            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if not event.is_directory:
                        try:
                            rel = str(Path(event.src_path).relative_to(watcher_self.wo_dir))
                        except ValueError:
                            rel = event.src_path
                        watcher_self.on_change(rel)

                def on_created(self, event):
                    self.on_modified(event)

                def on_moved(self, event):
                    if not event.is_directory:
                        try:
                            rel = str(Path(event.dest_path).relative_to(watcher_self.wo_dir))
                        except ValueError:
                            rel = event.dest_path
                        watcher_self.on_change(rel)

                def on_deleted(self, event):
                    if not event.is_directory:
                        try:
                            rel = str(Path(event.src_path).relative_to(watcher_self.wo_dir))
                        except ValueError:
                            rel = event.src_path
                        watcher_self.on_delete(rel)

            observer = Observer()
            observer.schedule(_Handler(), str(self.wo_dir), recursive=True)
            observer.start()
            log.info("WoWatcher: watchdog observer started")
            try:
                while not self._stop_event.is_set():
                    time.sleep(0.5)
            finally:
                observer.stop()
                observer.join()

        except ImportError:
            log.info("WoWatcher: watchdog not found, falling back to polling")
            self._start_poll_loop()

    # ------------------------------------------------------------------
    # Internal: polling fallback (all platforms)
    # ------------------------------------------------------------------

    def _build_snapshot(self) -> Dict[str, tuple]:
        """Return {rel_path: (size, mtime)} for all files under wo_dir."""
        snap: Dict[str, tuple] = {}
        for root, _dirs, files in os.walk(str(self.wo_dir)):
            for fname in files:
                full = Path(root) / fname
                try:
                    st = full.stat()
                    rel = str(full.relative_to(self.wo_dir))
                    snap[rel] = (st.st_size, st.st_mtime)
                except OSError:
                    pass
        return snap

    def _start_poll_loop(self) -> None:
        """Block, polling every poll_interval_s until stop() is called."""
        log.info(
            "WoWatcher: polling %s every %ds",
            self.wo_dir,
            self.poll_interval_s,
        )
        self._snapshot = self._build_snapshot()

        while not self._stop_event.wait(timeout=self.poll_interval_s):
            new_snap = self._build_snapshot()
            changed: Set[str] = set()
            deleted: Set[str] = set()

            for rel, info in new_snap.items():
                if rel not in self._snapshot or self._snapshot[rel] != info:
                    changed.add(rel)

            for rel in self._snapshot:
                if rel not in new_snap:
                    deleted.add(rel)

            for rel in changed:
                self.on_change(rel)
            for rel in deleted:
                self.on_delete(rel)

            self._snapshot = new_snap
