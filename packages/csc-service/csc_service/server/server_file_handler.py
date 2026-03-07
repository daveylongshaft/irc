import os
import time
from pathlib import Path
from csc_service.shared.secret import get_known_core_files
import re


class FileHandler:
    """
    Handles <begin file> … <end file> uploads with full whitespace preservation,
    safe-write enforcement, and protected-core-file restrictions.

    This class manages per-client upload sessions, buffers incoming file data,
    and performs secure writes to disk only after passing dual-layer validation.

    SECURITY FEATURES:
    ------------------
    1. **Root confinement** — All writes are restricted to the project root.
    2. **Dual-layer protection** — Protected core files (from secret.get_known_core_files)
       cannot be written or appended, either at start or completion of a session.
    3. **Versioning safety** — Existing files are versioned automatically
       before overwriting via `self.server.create_new_version`.
    4. **Upload Policy Enforcement** - Service module uploads are directed to `services/`.
       Other direct file uploads are directed to `staging_uploads/`.
    """
    
    # Regex for valid Python module names
    PYTHON_MODULE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def __init__(self, server):
        """
        Initializes the FileHandler.

        Args:
            server: The main Server instance for logging, versioning,
                    and access to project_root_dir.
        """
        self.server = server
        self.sessions = {}
        self.server.log("[FileHandler] Initialized upload subsystem with secure write protection.")
        
        # Define target directories
        self.services_dir = Path(self.server.project_root_dir) / "services"
        self.staging_dir = Path(self.server.project_root_dir) / "staging_uploads"
        
        self.services_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        self.server.log(f"[FileHandler] Services dir: {self.services_dir}")
        self.server.log(f"[FileHandler] Staging dir: {self.staging_dir}")


    # ==========================================================
    # START SESSION
    # ==========================================================
    def start_session(self, addr, line):
        """
        Begins a new upload session from a <begin file="..."> or <append file="..."> tag.

        SECURITY: Enforces upload policy: service modules go to services/, others to staging_uploads/.
        Also rejects writing to protected core files.

        Args:
            addr (tuple): The client's network address (IP, port).
            line (str): The received line containing the start tag.
        """
        text = line.strip()
        mode = "w"

        if text.startswith("<append file="):
            mode = "a"
            text = text.replace("<append file=", "", 1)
        elif text.startswith("<begin file="):
            text = text.replace("<begin file=", "", 1)
        else:
            self.server.log(f"[FileHandler] ⚠️ Invalid tag from {addr}: {line}")
            return

        if text.endswith(">"):
            text = text[:-1]
        raw_filename = text.strip().strip('"')
        
        # Enforce file upload policy
        # 1. Determine base directory based on filename pattern
        if raw_filename.endswith("_service.py") and Path(raw_filename).parent == Path("."):
            # This looks like a service module, direct it to services/
            module_name = raw_filename[:-len("_service.py")]
            if not self.PYTHON_MODULE_RE.match(module_name):
                self.server.log(f"[SECURITY] 🚫 Invalid Python module name '{module_name}' for service upload from {addr}.")
                self.server.send_to_client(addr, f"[ERROR] Upload denied. Invalid service module name.")
                return
            target_base_dir = self.services_dir
            filename_for_path = raw_filename
        else:
            # All other files go to staging_uploads/
            # Prevent directory traversal in filename if it's going to staging
            filename_for_path = Path(raw_filename).name # Only allow base name for staging
            if not filename_for_path:
                self.server.log(f"[SECURITY] 🚫 Empty filename for staging upload from {addr}.")
                self.server.send_to_client(addr, f"[ERROR] Upload denied. Empty filename.")
                return
            target_base_dir = self.staging_dir
            self.server.log(f"[FileHandler] Directing non-service or absolute path upload to staging: {raw_filename}")
            
        final_target_path = (target_base_dir / filename_for_path).resolve()
        
        root = Path(self.server.project_root_dir.resolve()).absolute()

        # Security Layer 1️⃣: prevent out-of-root and protected-core writes
        if not str(final_target_path).startswith(str(root)):
            self.server.log(f"[SECURITY] 🚫 Rejecting out-of-root path from {addr}: {final_target_path}")
            self.server.send_to_client(addr, f"[ERROR] Upload denied. Path outside project root.")
            return

        # Extract core filenames only once for performance
        protected_files = [Path(f).name for f in get_known_core_files()]
        if final_target_path.name in protected_files:
            self.server.log(f"[SECURITY] ❌ Upload rejected: '{final_target_path.name}' is a protected core file (layer 1).")
            self.server.send_to_client(addr, f"[ERROR] Upload denied. '{final_target_path.name}' is a protected system file.")
            return

        # If passed validation, start upload session
        self.sessions[addr] = {
            "path": final_target_path,
            "original_filename": raw_filename,
            "content": [],
            "mode": mode,
            "start_time": time.time(),
        }
        self.server.log(f"[FileHandler] BEGIN {mode.upper()} session from {addr} -> {final_target_path}")

    # ==========================================================
    # ABORT SESSION
    # ==========================================================
    def abort_session(self, addr):
        """
        Aborts an in-progress upload session, discarding its buffer and logging the event.
        """
        if addr in self.sessions:
            session = self.sessions.pop(addr, None)
            if session:
                self.server.log(f"[FileHandler] ⚠️ ABORTED upload for {addr}, target: {session.get('original_filename')}")
        else:
            self.server.log(f"[FileHandler] ⚠️ Abort requested but no session found for {addr}")

    # ==========================================================
    # PROCESS CHUNK
    # ==========================================================
    def process_chunk(self, addr, line):
        """
        Buffers a line of text for an active upload session.

        Logs every 50 lines for progress visibility.
        """
        if addr not in self.sessions:
            self.server.log(f"[FileHandler] ⚠️ CHUNK ignored (no active session) from {addr}")
            return

        processed_line = line.rstrip("\r\n") + "\n"
        session = self.sessions[addr]
        session["content"].append(processed_line)

        if len(session["content"]) % 50 == 0:
            self.server.log(
                f"[FileHandler] Buffered {len(session['content'])} lines for {session['original_filename']} from {addr}"
            )

    # ==========================================================
    # COMPLETE SESSION
    # ==========================================================
    def complete_session(self, addr):
        """
        Completes an upload session, performs final security validation,
        and safely writes the file to disk with versioning.

        SECURITY: Denies overwriting protected core files even if the session
        was somehow started (Layer 2 verification).

        Returns:
            str: Status message indicating success or reason for denial.
        """
        session = self.sessions.pop(addr, None)
        if not session:
            self.server.log(f"[FileHandler] ⚠️ No active session to complete for {addr}")
            return "No active session."

        path = Path(session["path"]).absolute()
        mode = session["mode"]
        filename = session["original_filename"]
        full_content = "".join(session["content"])
        root = Path(self.server.project_root_dir.resolve()).absolute()
        protected_files = [Path(f).name for f in get_known_core_files()]

        # Security Layer 2️⃣: recheck protected files
        if path.name in protected_files:
            self.server.log(f"[SECURITY] ❌ Write denied for protected core file '{filename}' from {addr} (layer 2).")
            self.server.send_to_client(addr, f"[ERROR] Write denied. '{filename}' is a protected system file.")
            return f"Write denied for protected core file '{filename}'."

        # Out-of-root check again for redundancy
        if not str(path).startswith(str(root)):
            self.server.log(f"[SECURITY] 🚫 Out-of-root write blocked: {path}")
            return f"Write outside project root forbidden for '{filename}'."

        try:
            # Create version backup before overwrite
            if path.exists() and mode == 'w':
                self.server.create_new_version(str(path))

            # Write file safely
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, mode, encoding="utf-8", newline="") as f:
                f.write(full_content)

            elapsed = time.time() - session["start_time"]
            self.server.log(
                f"[FileHandler] ✅ WROTE {len(full_content)} chars to {path} "
                f"in {elapsed:.2f}s (mode={mode})"
            )
            return f"File '{filename}' saved successfully."

        except Exception as e:
            self.server.log(f"[FileHandler ERROR] ❌ Exception while writing {filename}: {e}")
            return f"Error saving file '{filename}': {e}"
