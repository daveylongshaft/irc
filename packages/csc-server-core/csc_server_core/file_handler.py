import os
import time
import re
from pathlib import Path
from csc_server_core.irc import SERVER_NAME

class FileHandler:
    """Handles <begin file> … <end file> uploads via IRC."""

    PYTHON_MODULE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def __init__(self, server):
        self.server = server
        self.sessions = {}
        self.project_root = Path(getattr(server, "project_root_dir", Path.cwd()))

        self.services_dir = self.project_root / "services"
        self.staging_dir = self.project_root / "staging_uploads"

        self.services_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def start_session(self, addr, line):
        text = line.strip()
        mode = "w"

        if text.startswith("<append file="):
            mode = "a"
            text = text.replace("<append file=", "", 1)
        elif text.startswith("<begin file="):
            text = text.replace("<begin file=", "", 1)
        else:
            return

        if text.endswith(">"):
            text = text[:-1]
        raw_filename = text.strip().strip('"')

        if raw_filename.endswith(".py"):
            target_base_dir = self.services_dir
            filename_for_path = raw_filename
        else:
            filename_for_path = Path(raw_filename).name
            target_base_dir = self.staging_dir

        final_target_path = (target_base_dir / filename_for_path).resolve()

        # Security: prevent out-of-root
        if not str(final_target_path).startswith(str(self.project_root.resolve())):
            self.server.log(f"[SECURITY] 🚫 Rejecting out-of-root path from {addr}: {final_target_path}")
            return

        self.sessions[addr] = {
            "path": final_target_path,
            "original_filename": raw_filename,
            "content": [],
            "mode": mode,
            "start_time": time.time(),
        }
        self.server.log(f"[FileHandler] BEGIN {mode.upper()} session from {addr} -> {final_target_path}")

    def abort_session(self, addr):
        self.sessions.pop(addr, None)

    def process_chunk(self, addr, line):
        if addr not in self.sessions:
            return
        processed_line = line.rstrip("\r\n") + "\n"
        self.sessions[addr]["content"].append(processed_line)

    def complete_session(self, addr):
        session = self.sessions.pop(addr, None)
        if not session:
            return "No active session."

        path = Path(session["path"])
        mode = session["mode"]
        full_content = "".join(session["content"])

        try:
            if path.exists() and mode == 'w':
                if hasattr(self.server, "create_new_version"):
                    self.server.create_new_version(str(path))

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, mode, encoding="utf-8", newline="") as f:
                f.write(full_content)

            self.server.log(f"[FileHandler] ✅ WROTE {len(full_content)} chars to {path} (mode={mode})")
            return f"File '{session['original_filename']}' saved successfully."
        except Exception as e:
            self.server.log(f"[FileHandler ERROR] ❌ Exception while writing: {e}")
            return f"Error saving file: {e}"
