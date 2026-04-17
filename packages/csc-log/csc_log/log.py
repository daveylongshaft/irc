import os
import time
import inspect
from pathlib import Path
from csc_root import Root


def _get_logs_dir() -> Path:
    """Resolve logs directory without requiring Platform() to be instantiated.

    Resolution order (never raises):
    1. CSC_LOGS env var (set by Platform.export_paths())
    2. platform.json runtime.temp_root → derive PROJECT_ROOT → PROJECT_ROOT/logs
    3. Walk up from this file to find csc-service.json → PROJECT_ROOT/logs
    4. Fall back to current working directory
    """
    # 1. Env var — fastest path, set once Platform is up
    env = os.environ.get("CSC_LOGS", "")
    if env:
        try:
            p = Path(env)
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass

    # 2 & 3. Walk up from this file to find PROJECT_ROOT
    try:
        here = Path(__file__).resolve().parent
        for _ in range(12):
            if (here / "csc-service.json").exists() or (here / "etc" / "csc-service.json").exists():
                p = here / "logs"
                p.mkdir(parents=True, exist_ok=True)
                return p
            if here == here.parent:
                break
            here = here.parent
    except Exception:
        pass

    # 4. Fallback — write next to process cwd
    return Path.cwd()


class Log(Root):
    """
    Extends the root class.

    Provides a standardized base for logging, intended to be overridden by
    all higher-level classes.
    """

    def __init__(self, server=None):
        super().__init__()
        self.name = "log"
        # Set a default log_file that subclasses can override.
        # The log() method will use self.name if subclass sets it after calling super().__init__()
        self.log_file = f"{self.name}.log"

    @classmethod
    def set_platform_log_dir(cls, log_dir):
        """Called by Platform after path detection — no-op here since log.py
        resolves its own path via _get_logs_dir() on every write."""
        pass

    def log(self, message: str, level: str = "INFO"):
        """
        Logs a message to per-service log file and prints to console.

        - What it does: Formats a log entry with a timestamp, level, and the
          calling class's name, prints it to the console, and then appends it
          to the service-specific log file (self.log_file, which defaults to self.name + .log).
        - Arguments:
            - `message` (str): The message to be logged.
            - `level` (str): Severity level (default: INFO).
        - What calls it: Called by various methods throughout the system.
        - What it calls: `time.strftime()`, `open()`.
        """
        timestamp = time.strftime( "%Y-%m-%d %H:%M:%S" )
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] [{level}] {message}\n"

        # Print to the local console for immediate feedback
        if not os.environ.get("CSC_QUIET"):
            print( log_entry.strip() )

        try:
            log_path = _get_logs_dir() / self.log_file
            with open(log_path, "a") as f:
                f.write(log_entry)
        except Exception as e:
            if not os.environ.get("CSC_QUIET"):
                print(f"CRITICAL: Failed to write to log file '{self.log_file}': {e}")


    def runtime(self, message: str):
        """Write a compact line to logs/runtime.log for the #runtime IRC feed.

        Format: [HH:MM:SS] [self.name] message
        Uses Data._write_runtime() when available (MRO), falls back to direct append.
        """
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{self.name}] {message}"
        if hasattr(self, "_write_runtime"):
            self._write_runtime(line)
        else:
            try:
                log_dir = _get_logs_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "runtime.log", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    def help(self, method_name=None):
        """
        Returns help for the class or a specific method as a string.

        With no args: lists all public methods with signature and first line of docstring.
        With method_name arg: shows the full docstring of that method.
        """
        self.log( "Displaying log help information." )
        lines = []
        if method_name:
            m = getattr(self, method_name, None)
            if m is None or method_name.startswith('_'):
                lines.append( f"No method '{method_name}' found on {self.__class__.__name__}" )
            else:
                doc = inspect.getdoc(m) or "No docstring."
                sig = str(inspect.signature(m))
                lines.append( f"--- {self.__class__.__name__}.{method_name}{sig} ---" )
                lines.append( doc )
        else:
            lines.append( f"--- Help for {self.__class__.__name__} ---" )
            for name, m in inspect.getmembers(self, predicate=inspect.ismethod):
                if name.startswith('_'):
                    continue
                sig = str(inspect.signature(m))
                doc = inspect.getdoc(m) or ""
                first_line = doc.splitlines()[0] if doc else ""
                lines.append( f"  {name}{sig}: {first_line}" )
        result = "\n".join(lines)
        print( result )
        return result

    def _tail_log_file(self, path, offset: int = 0):
        """Read new lines from a disk log file starting at byte offset.

        Returns (lines: list[str], new_offset: int).

        Handles: file not found ([], 0), truncated files (resets to end).
        Uses binary mode so stat().st_size byte offsets match seek() exactly
        (text mode on Windows translates CRLF, breaking offset alignment).
        Only returns complete lines — partial lines at EOF are held for the
        next poll.

        csc_data.Data overrides this to support VFS-backed enc pathspecs
        (paths containing '::') transparently.
        """
        path = Path(path)
        try:
            if not path.exists():
                return [], 0
            current_size = path.stat().st_size
            if current_size < offset:
                # File was truncated — reset to current end
                return [], current_size
            if current_size == offset:
                return [], offset
            with open(path, "rb") as f:
                f.seek(offset)
                raw = f.read(current_size - offset)
            text = raw.decode("utf-8", errors="ignore")
            if not text.endswith("\n"):
                last_nl = text.rfind("\n")
                if last_nl == -1:
                    return [], offset
                complete = text[:last_nl + 1]
                new_offset = offset + len(complete.encode("utf-8"))
                return [ln + "\n" for ln in complete.splitlines()], new_offset
            return [ln + "\n" for ln in text.splitlines()], current_size
        except Exception as e:
            if not os.environ.get("CSC_QUIET"):
                print(f"[_tail_log_file] Error reading {path}: {e}")
            return [], offset

    def test(self):
        """
        Runs a base self-test for the class.

        - What it does: Logs that the test command was called. This method is
          intended to be extended by subclasses to provide specific tests.
        - Arguments: None.
        - What calls it: Typically called by the command handling system when a
          user issues a `test` command.
        - What it calls: `self.log()`.
        """
        self.log( f"Running base self-test for {self.__class__.__name__}." )
        return True

if __name__ == '__main__':
    log = Log()
    log.run()

