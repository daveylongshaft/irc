import shutil
import time
import re
from pathlib import Path
from csc_platform import Platform
from csc_server_core.irc import SERVER_NAME


class FileHandler:
    """Handles <begin file> ... <end file> uploads via IRC.

    All uploads go to staging first. On completion the content is validated:
      - file= value (strip .py if present) must be a valid Python identifier -> expected class name
      - content must contain exactly that class name as a top-level class definition
    On success the staged file is moved to services/<ClassName>_service.py.
    On failure the staged file is deleted and the rejection reason is returned.
    """

    PYTHON_MODULE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    CLASS_RE = re.compile(r'^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:(]', re.MULTILINE)

    def __init__(self, server):
        self.server = server
        self.sessions = {}
        self.project_root = Platform.PROJECT_ROOT

        self.services_dir = Platform.get_services_dir()
        self.staging_dir = Platform.PROJECT_ROOT / "tmp" / "staging_uploads"

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

        # Derive expected class name: strip .py, reject anything else with a dot
        stem = raw_filename[:-3] if raw_filename.endswith(".py") else raw_filename

        if not self.PYTHON_MODULE_RE.match(stem):
            reason = f"Invalid module name '{raw_filename}': must be a valid Python identifier (optionally ending in .py)"
            self.server.log(f"[FileHandler] REJECTED from {addr}: {reason}")
            self.sessions[addr] = {"rejected": True, "reason": reason}
            return

        staging_path = (self.staging_dir / f"{stem}.py").resolve()

        # Security: prevent out-of-root
        if not str(staging_path).startswith(str(self.project_root.resolve())):
            self.server.log(f"[SECURITY] [BLOCKED] out-of-root staging path from {addr}: {staging_path}")
            return

        self.sessions[addr] = {
            "path": staging_path,
            "stem": stem,
            "original_filename": raw_filename,
            "content": [],
            "mode": mode,
            "start_time": time.time(),
        }
        self.server.log(f"[FileHandler] BEGIN {mode.upper()} from {addr} -> staging/{stem}.py (expect class {stem})")

    def abort_session(self, addr):
        session = self.sessions.pop(addr, None)
        if session and not session.get("rejected"):
            staging = Path(session["path"])
            if staging.exists():
                staging.unlink(missing_ok=True)

    def process_chunk(self, addr, line):
        session = self.sessions.get(addr)
        if not session or session.get("rejected"):
            return
        session["content"].append(line.rstrip("\r\n") + "\n")

    def complete_session(self, addr):
        session = self.sessions.pop(addr, None)
        if not session:
            return "No active session."

        if session.get("rejected"):
            return f"Upload rejected: {session['reason']}"

        stem = session["stem"]
        staging_path = Path(session["path"])
        mode = session["mode"]
        new_content = "".join(session["content"])

        # For append: merge with existing deployed file so validation sees the full result
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

        # Validate: must contain class <stem>
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

        # Security: final path must be inside project root
        if not str(final_path).startswith(str(self.project_root.resolve())):
            staging_path.unlink(missing_ok=True)
            return "Rejected: resolved target path is outside project root"

        # Backup existing deployed file before replacing
        if final_path.exists() and hasattr(self.server, "create_new_version"):
            self.server.create_new_version(str(final_path))

        # Move staging -> services/<stem>_service.py
        try:
            staging_path.rename(final_path)
        except OSError:
            # Cross-device rename (different filesystems); fall back to copy+delete
            try:
                shutil.copy2(staging_path, final_path)
                staging_path.unlink(missing_ok=True)
            except Exception as e:
                return f"Error deploying to services: {e}"

        self.server.log(f"[FileHandler] [OK] Deployed staging/{stem}.py -> services/{stem}_service.py")
        return f"Service '{stem}' deployed to services/{stem}_service.py"
