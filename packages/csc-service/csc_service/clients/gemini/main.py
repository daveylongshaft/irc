"""Entry point for the CSC Gemini autonomous AI client.

This module serves as the main entry point for the Gemini autonomous AI client
in the client-server-commander (CSC) ecosystem. It configures the working directory,
sets up the Python import path, and launches the Gemini client.

Responsibilities:
    - Set working directory to application directory for data file access
    - Configure sys.path to enable imports from parent directory
    - Import and instantiate the Gemini class
    - Run the Gemini client main loop

Environment Setup:
    - Changes CWD to the directory containing this file
    - Adds parent directory to sys.path for csc_gemini imports
    - Expects csc_gemini package to be in parent directory
    - Expects csc_service.clients.client and csc_service.shared packages in parent directory

Configuration:
    - Reads gemini_config.json from working directory
    - Reads Google Gemini API key from /opt/csc/.env (GEMINI_API_KEY)
    - Falls back to environment variables and config file

Threading:
    Not applicable at module level. Threading is handled by Gemini class.

Side Effects:
    - Changes process working directory (os.chdir)
    - Modifies sys.path globally
    - Imports csc_gemini.gemini module (triggers module-level code)
    - Gemini.run() blocks indefinitely until interrupted

Usage:
    python main.py                # Run as script
    python -m csc_gemini.main     # Run as module
    systemctl start csc-gemini    # Run as systemd service (daemon mode)

Exit Codes:
    - 0: Normal exit (Ctrl+C or client shutdown)
    - 1: Import error, google-generativeai package missing, or client initialization failure

Dependencies:
    - google-generativeai: Required for Gemini API access (pip install google-generativeai)
    - csc_service.clients.client: Base client class
    - csc_service.shared: Shared utilities (secret.py, irc.py)
"""
import sys
import os

_gemini_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_gemini_dir)

_parent = os.path.dirname(_gemini_dir)
# Prioritize local packages over system packages - but keep dependencies
if _parent in sys.path:
    sys.path.remove(_parent)
sys.path.insert(0, _parent)

def main():
    """Initialize and run the Gemini autonomous AI client.

    Args:
        None: Configuration is read from gemini_config.json in the working directory.

    Returns:
        None: Does not return; blocks indefinitely in Gemini.run() until interrupted.

    Raises:
        ImportError: If csc_gemini.gemini module or google-generativeai package cannot be imported.
        SystemExit: If Gemini.__init__() fails and calls sys.exit(1).
        KeyboardInterrupt: If user presses Ctrl+C (not caught here, propagates).
        Exception: Any exception from Gemini.__init__() or Gemini.run() propagates.

    Data:
        - Reads: None directly (Gemini reads gemini_config.json and .env)
        - Writes: None
        - Mutates: None

    Side effects:
        - Logging: Gemini logs to Gemini.log file
        - Network I/O:
            - Opens UDP socket and connects to CSC server (default 127.0.0.1:9525)
            - Connects to Google Gemini API (generativelanguage.googleapis.com)
        - Disk writes:
            - Writes Gemini.log (application log)
            - Writes Gemini_state.json (client state persistence)
        - Thread safety: Not applicable; this is the main thread entry point.
          Gemini.run() manages multiple daemon threads internally (input handler,
          message worker, heartbeat loop).

    Children:
        - from csc_gemini.gemini import Gemini: Imports Gemini class
        - Gemini.__init__(): Instantiates client, connects to Gemini API
        - Gemini.run(): Starts client main loop (blocks indefinitely)

    Parents:
        - __main__ block: Calls this when script is executed directly
        - systemd service: May call this as entry point for daemon

    Execution Flow:
        1. Import Gemini class from csc_gemini.gemini
        2. Instantiate Gemini() - reads config, connects to server and Gemini API
        3. Call Gemini.run() - starts threads, blocks in main loop
        4. Never returns normally; exit via exception or signal

    Daemon Mode:
        If stdin is not a TTY (e.g., systemd service), Gemini runs in daemon mode
        with input handler sleeping indefinitely while message worker processes
        server messages and AI responses.

    Multi-Agent Collaboration:
        Gemini works alongside Claude AI client in the CSC ecosystem. Both agents
        collaborate on tasks, review each other's work, and coordinate via the
        chatline and workflow system.
    """
    # Import from local packages (sys.path already prioritizes /opt/csc/packages)
    from gemini import Gemini
    Gemini().run()

if __name__ == "__main__":
    main()
