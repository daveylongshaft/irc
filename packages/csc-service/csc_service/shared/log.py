import os
import time
from pathlib import Path
from csc_service.shared.root import Root


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
        self.log_file = f"{self.name}.log"

    @classmethod
    def set_platform_log_dir(cls, log_dir):
        """Called by Platform after path detection — no-op here since log.py
        resolves its own path via _get_logs_dir() on every write."""
        pass

    def log(self, message: str):
        """
        Logs a message to the central project log file and prints to console.

        - What it does: Formats a log entry with a timestamp and the calling class's
          name, prints it to the console, and then appends it to the log file.
        - Arguments:
            - `message` (str): The message to be logged.
        - What calls it: Called by various methods throughout the system.
        - What it calls: `time.strftime()`, `open()`.
        """
        timestamp = time.strftime( "%Y-%m-%d %H:%M:%S" )
        class_name = self.__class__.__name__
        log_entry = f"[{timestamp}] [{class_name}] {message}\n"

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


    def help(self):
        """
        Displays base help information for the class.

        - What it does: Logs that the help command was called and prints basic
          help information to the console. This method is intended to be
          extended by subclasses.
        - Arguments: None.
        - What calls it: Typically called by the command handling system when a
          user issues a `help` command.
        - What it calls: `self.log()`, `print()`.
        """
        self.log( "Displaying log help information." )
        print( f"\n--- Help for {self.__class__.__name__} ---" )
        print( "  help(): Displays this message." )
        print( "  test(): Runs the module's internal self-test." )

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

