"""Entry point for the CSC Docker Model Runner Bot autonomous AI client.

This module serves as the main entry point for the Docker Model Runner Bot
autonomous AI client in the client-server-commander (CSC) ecosystem. It configures
the working directory, sets up the Python import path, and launches the dMrBot client.

Responsibilities:
    - Set working directory to application directory for data file access
    - Configure sys.path to enable imports from parent directory
    - Import and instantiate the DMrBot class
    - Run the DMrBot client main loop

Environment Setup:
    - Changes CWD to the directory containing this file
    - Adds parent directory to sys.path for csc_dmrbot imports
    - Expects csc_dmrbot package to be in parent directory
    - Expects csc_service.clients.client and csc_service.shared packages in parent directory

Configuration:
    - Reads settings.json from working directory
    - Configures Docker Model Runner API endpoint (default: http://localhost:12434/engines/v1)
    - Configures model name and parameters

Threading:
    Not applicable at module level. Threading is handled by DMrBot class.

Side Effects:
    - Changes process working directory (os.chdir)
    - Modifies sys.path globally
    - Imports csc_dmrbot.dmrbot module (triggers module-level code)
    - DMrBot.run() blocks indefinitely until interrupted

Usage:
    python main.py                # Run as script
    python -m csc_dmrbot.main     # Run as module
    systemctl start csc-dmrbot    # Run as systemd service (daemon mode)

Exit Codes:
    - 0: Normal exit (Ctrl+C or client shutdown)
    - 1: Import error, OpenAI package missing, or client initialization failure

Dependencies:
    - openai: Required for Docker Model Runner API access (pip install openai)
    - csc_service.clients.client: Base client class
    - csc_service.shared: Shared utilities (secret.py, irc.py)
"""
import sys
import os

_dmrbot_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_dmrbot_dir)

_parent = os.path.dirname(_dmrbot_dir)
if _parent not in sys.path:
    sys.path.append(_parent)

def main():
    """Initialize and run the Docker Model Runner Bot autonomous AI client.

    Args:
        None: Configuration is read from settings.json in the working directory.

    Returns:
        None: Does not return; blocks indefinitely in DMrBot.run() until interrupted.

    Raises:
        ImportError: If csc_dmrbot.dmrbot module or openai package cannot be imported.
        SystemExit: If DMrBot.__init__() fails and calls sys.exit(1).
        KeyboardInterrupt: If user presses Ctrl+C (not caught here, propagates).
        Exception: Any exception from DMrBot.__init__() or DMrBot.run() propagates.

    Data:
        - Reads: None directly (DMrBot reads settings.json)
        - Writes: None
        - Mutates: None

    Side effects:
        - Logging: DMrBot logs to dMrBot.log file
        - Network I/O:
            - Opens UDP socket and connects to CSC server (default 127.0.0.1:9525)
            - Connects to Docker Model Runner API (default http://localhost:12434/engines/v1)
        - Disk writes:
            - Writes dMrBot.log (application log)
            - Writes dMrBot_state.json (client state persistence)
        - Thread safety: Not applicable; this is the main thread entry point.
          DMrBot.run() manages multiple daemon threads internally (input handler,
          message worker).

    Children:
        - from csc_dmrbot.dmrbot import DMrBot: Imports DMrBot class
        - DMrBot.__init__(): Instantiates client, connects to Docker Model Runner
        - DMrBot.run(): Starts client main loop (blocks indefinitely)

    Parents:
        - __main__ block: Calls this when script is executed directly
        - systemd service: May call this as entry point for daemon

    Execution Flow:
        1. Import DMrBot class from csc_dmrbot.dmrbot
        2. Instantiate DMrBot() - reads config, connects to server and Docker Model Runner
        3. Call DMrBot.run() - starts threads, blocks in main loop
        4. Never returns normally; exit via exception or signal

    Daemon Mode:
        If stdin is not a TTY (e.g., systemd service), DMrBot runs in daemon mode
        with input handler sleeping indefinitely while message worker processes
        server messages and AI responses.
    """
    from dmrbot import DMrBot
    DMrBot().run()

if __name__ == "__main__":
    main()
