import re
import shutil
import time
from pathlib import Path


class BaseFileHandler:
    """Shared staging/validate/deploy logic for service module uploads.

    Both the server FileHandler and client ClientFileHandler subclass this.
    Differences (log function, paths, backup callback) are injected at init.

    Sessions are keyed by nick so multiple senders can upload simultaneously.

    Upload flow:
      start_session  -> validate name, open staging/<stem>.py
      process_chunk  -> buffer lines
      complete_session -> write staging, validate class <stem>, deploy to
                         services/<stem>_service.py, delete staging on failure
    """

    PYTHON_MODULE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    CLASS_RE = re.compile(r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]', re.MULTILINE)

    def __init__(self, log_fn, project_root, services_dir, staging_dir, backup_fn=None):
        """
        log_fn      -- callable(str) for logging
        project_root -- Path, used for security confinement
        services_dir -- Path, where <stem>_service.py is deployed
        staging_dir  -- Path, where uploads are buffered before validation
        backup_fn    -- optional callable(str path) to version existing files
        """
        self.sessions = {}
        self._log = log_fn
        self.project_root = Path(project_root).resolve()
        self.services_dir = Path(services_dir)
        self.staging_dir = Path(staging_dir)
        self._backup_fn = backup_fn
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_session(self, nick):
        return nick in self.sessions

    # Alias used by existing client code
    has_active_session = has_session

    def start_session(self, nick, line):
        """Parse the <begin|append file=...> tag and open a staging session."""
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

        stem = raw_filename[:-3] if raw_filename.endswith(".py") else raw_filename

        if not self.PYTHON_MODULE_RE.match(stem):
            reason = (
                f"Invalid module name '{raw_filename}': "
                f"must be a valid Python identifier (optionally ending in .py)"
            )
            self._log(f"[FileHandler] REJECTED from {nick}: {reason}")
            self.sessions[nick] = {"rejected": True, "reason": reason}
            return

        staging_path = (self.staging_dir / f"{stem}.py").resolve()

        if not str(staging_path).startswith(str(self.project_root)):
            self._log(f"[SECURITY] [BLOCKED] out-of-root staging path from {nick}: {staging_path}")
            return

        self.sessions[nick] = {
            "path": staging_path,
            "stem": stem,
            "original_filename": raw_filename,
            "content": [],
            "mode": mode,
            "start_time": time.time(),
        }
        self._log(f"[FileHandler] BEGIN {mode.upper()} from {nick} -> staging/{stem}.py (expect class {stem})")

    def process_chunk(self, nick, line):
        session = self.sessions.get(nick)
        if not session or session.get("rejected"):
            return
        session["content"].append(line.rstrip("\r\n") + "\n")

    def abort_session(self, nick):
        session = self.sessions.pop(nick, None)
        if session and not session.get("rejected"):
            Path(session["path"]).unlink(missing_ok=True)
            self._log(f"[FileHandler] ABORTED upload from {nick}")

    def complete_session(self, nick):
        """Validate staged content and deploy to services/ or return rejection reason."""
        session = self.sessions.pop(nick, None)
        if not session:
            return "No active session."

        if session.get("rejected"):
            return f"Upload rejected: {session['reason']}"

        stem = session["stem"]
        staging_path = Path(session["path"])
        mode = session["mode"]
        new_content = "".join(session["content"])

        # For append: merge with the currently deployed file
        final_path = (self.services_dir / f"{stem}_service.py").resolve()
        if mode == "a" and final_path.exists():
            try:
                existing = final_path.read_text(encoding="utf-8")
            except Exception as e:
                return f"Error reading existing service for append: {e}"
            full_content = existing + new_content
        else:
            full_content = new_content

        # Write combined content to staging
        try:
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            with open(staging_path, "w", encoding="utf-8", newline="") as f:
                f.write(full_content)
        except Exception as e:
            return f"Error writing to staging: {e}"

        # Validate: content must define class <stem>
        classes_found = self.CLASS_RE.findall(full_content)
        if not classes_found:
            staging_path.unlink(missing_ok=True)
            return f"Rejected '{session['original_filename']}': no class definition found in content"

        if stem not in classes_found:
            staging_path.unlink(missing_ok=True)
            found_list = ", ".join(classes_found)
            return (
                f"Rejected '{session['original_filename']}': "
                f"class name mismatch -- expected class {stem}, found: {found_list}"
            )

        if not str(final_path).startswith(str(self.project_root)):
            staging_path.unlink(missing_ok=True)
            return "Rejected: resolved target path is outside project root"

        if final_path.exists() and self._backup_fn:
            self._backup_fn(str(final_path))

        try:
            staging_path.rename(final_path)
        except OSError:
            try:
                shutil.copy2(staging_path, final_path)
                staging_path.unlink(missing_ok=True)
            except Exception as e:
                return f"Error deploying to services: {e}"

        elapsed = time.time() - session["start_time"]
        msg = f"Service '{stem}' deployed to services/{stem}_service.py ({len(full_content)} bytes, {elapsed:.2f}s)"
        self._log(f"[FileHandler] [OK] {msg}")
        return msg
