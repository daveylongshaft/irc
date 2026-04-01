import os
import time
from pathlib import Path

class ClientFileHandler:
    """
    Handles file uploads sent TO this client from other users.
    Implements root confinement, safe-write enforcement, and versioning.
    """
    def __init__(self, client):
        self.client = client
        self.sessions = {}
        # Use project root for confinement, same as server
        self.root = Path(self.client.project_root_dir).resolve()
        self.client.log(f"[ClientFileHandler] Initialized. Root: {self.root}")

    def has_active_session(self, nick):
        return nick in self.sessions

    def start_session(self, addr_or_nick, line):
        """
        Begins a new upload session from a <begin file="..."> or <append file="..."> tag.
        """
        text = line.strip()
        mode = "w"

        if text.startswith("<append file="):
            mode = "a"
            text = text.replace("<append file=", "", 1)
        elif text.startswith("<begin file="):
            text = text.replace("<begin file=", "", 1)
        else:
            self.client.log(f"[ClientFileHandler] Invalid tag from {addr_or_nick}: {line}")
            return

        if text.endswith(">"):
            text = text[:-1]
        filename = text.strip().strip('"')

        # Resolve target path relative to project root
        target_path = Path((self.root / filename).resolve())

        # Security: Root confinement
        if not str(target_path).startswith(str(self.root)):
            self.client.log(f"[SECURITY] Rejecting out-of-root path from {addr_or_nick}: {filename}")
            return

        # Security: Protected core files (mimic server logic)
        # For client, we might want to protect client.py, etc.
        protected = ["client.py", "network.py", "data.py", "version.py", "root.py", "secret.py"]
        if target_path.name in protected:
            self.client.log(f"[SECURITY] Upload rejected: '{filename}' is a protected core file.")
            return

        self.sessions[addr_or_nick] = {
            "path": target_path,
            "filename": filename,
            "content": [],
            "mode": mode,
            "start_time": time.time(),
        }
        self.client.log(f"[ClientFileHandler] BEGIN {mode.upper()} session from {addr_or_nick} -> {target_path}")

    def process_chunk(self, addr_or_nick, line):
        """Buffers a line of text for an active upload session."""
        if addr_or_nick not in self.sessions:
            return

        processed_line = line.rstrip("\r\n") + "\n"
        self.sessions[addr_or_nick]["content"].append(processed_line)

    def complete_session(self, addr_or_nick):
        """Completes the session, versions if needed, and writes to disk."""
        session = self.sessions.pop(addr_or_nick, None)
        if not session:
            return "No active session."

        path = session["path"]
        mode = session["mode"]
        filename = session["filename"]
        full_content = "".join(session["content"])

        try:
            # Version before overwrite
            if path.exists() and mode == 'w':
                # Client inherits from Version, so it has create_new_version
                self.client.create_new_version(str(path))

            # Ensure parent directories exist
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(path, mode, encoding="utf-8", newline="") as f:
                f.write(full_content)

            elapsed = time.time() - session["start_time"]
            msg = f"File '{filename}' saved successfully ({len(full_content)} bytes, {elapsed:.2f}s)."
            self.client.log(f"[ClientFileHandler] {msg}")
            return msg

        except Exception as e:
            err = f"Error saving file '{filename}': {e}"
            self.client.log(f"[ClientFileHandler ERROR] {err}")
            return err

    def abort_session(self, addr_or_nick):
        """Aborts an in-progress upload session."""
        session = self.sessions.pop(addr_or_nick, None)
        if session:
            self.client.log(f"[ClientFileHandler] ABORTED upload from {addr_or_nick}")