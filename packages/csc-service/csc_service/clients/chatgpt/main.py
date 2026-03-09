"""Entry point for the CSC ChatGPT autonomous AI client.

This module serves as the main entry point for the ChatGPT autonomous AI client
in the client-server-commander (CSC) ecosystem. It configures the working directory,
sets up the Python import path, and launches the ChatGPT client.

Responsibilities:
    - Set working directory to application directory for data file access
    - Configure sys.path to enable imports from parent directory
    - Import and instantiate the ChatGPT class
    - Run the ChatGPT client main loop

Environment Setup:
    - Changes CWD to the directory containing this file
    - Adds parent directory to sys.path for csc_chatgpt imports
    - Expects csc_chatgpt package to be in parent directory
    - Expects csc_service.clients.client and csc_service.shared packages in parent directory

Configuration:
    - Reads chatgpt_config.json from working directory
    - Reads OpenAI API key from /opt/csc/.env (CHATGPT_API_KEY or OPENAI_API_KEY)
    - Falls back to environment variables and config file

Threading:
    Not applicable at module level. Threading is handled by ChatGPT class.

Side Effects:
    - Changes process working directory (os.chdir)
    - Modifies sys.path globally
    - Imports csc_chatgpt.chatgpt module (triggers module-level code)
    - ChatGPT.run() blocks indefinitely until interrupted

Usage:
    python main.py                # Run as script
    python -m csc_chatgpt.main    # Run as module
    systemctl start csc-chatgpt   # Run as systemd service (daemon mode)

Exit Codes:
    - 0: Normal exit (Ctrl+C or client shutdown)
    - 1: Import error, OpenAI package missing, or client initialization failure

Dependencies:
    - openai: Required for ChatGPT API access (pip install openai)
    - csc_service.clients.client: Base client class
    - csc_service.shared: Shared utilities (secret.py, irc.py)
"""
import sys
import os

_chatgpt_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_chatgpt_dir)

_parent = os.path.dirname(_chatgpt_dir)
if _parent not in sys.path:
    sys.path.append(_parent)

def main():
    """Initialize and run the ChatGPT autonomous AI client.

    Args:
        None: Configuration is read from chatgpt_config.json in the working directory.

    Returns:
        None: Does not return; blocks indefinitely in ChatGPT.run() until interrupted.

    Raises:
        ImportError: If csc_chatgpt.chatgpt module or openai package cannot be imported.
        SystemExit: If ChatGPT.__init__() fails and calls sys.exit(1).
        KeyboardInterrupt: If user presses Ctrl+C (not caught here, propagates).
        Exception: Any exception from ChatGPT.__init__() or ChatGPT.run() propagates.

    Data:
        - Reads: None directly (ChatGPT reads chatgpt_config.json and .env)
        - Writes: None
        - Mutates: None

    Side effects:
        - Logging: ChatGPT logs to ChatGPT.log file
        - Network I/O:
            - Opens UDP socket and connects to CSC server (default 127.0.0.1:9525)
            - Connects to OpenAI API (api.openai.com)
        - Disk writes:
            - Writes ChatGPT.log (application log)
            - Writes ChatGPT_state.json (client state persistence)
        - Thread safety: Not applicable; this is the main thread entry point.
          ChatGPT.run() manages multiple daemon threads internally (input handler,
          message worker).

    Children:
        - from csc_chatgpt.chatgpt import ChatGPT: Imports ChatGPT class
        - ChatGPT.__init__(): Instantiates client, connects to OpenAI API
        - ChatGPT.run(): Starts client main loop (blocks indefinitely)

    Parents:
        - __main__ block: Calls this when script is executed directly
        - systemd service: May call this as entry point for daemon

    Execution Flow:
        1. Import ChatGPT class from csc_chatgpt.chatgpt
        2. Instantiate ChatGPT() - reads config, connects to server and OpenAI
        3. Call ChatGPT.run() - starts threads, blocks in main loop
        4. Never returns normally; exit via exception or signal

    Daemon Mode:
        If stdin is not a TTY (e.g., systemd service), ChatGPT runs in daemon mode
        with input handler sleeping indefinitely while message worker processes
        server messages and AI responses.
    """
    from csc_chatgpt.chatgpt import ChatGPT
    ChatGPT().run()

if __name__ == "__main__":
    main()
