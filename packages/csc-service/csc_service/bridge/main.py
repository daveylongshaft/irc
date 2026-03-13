"""CSC Bridge Daemon - Entry Point

This module serves as the main entry point for the CSC bridge proxy daemon. The bridge
acts as a protocol translator and proxy between different network transports (TCP, UDP)
and the CSC server, enabling clients to connect via multiple protocols.

Responsibilities:
    - Configure working directory for data file access
    - Set up logging for bridge operations
    - Load configuration from config.json
    - Instantiate inbound transports (TCP, UDP listeners)
    - Instantiate outbound transport (UDP to server)
    - Create and start Bridge instance
    - Keep main thread alive while daemon threads run

Architecture:
    Bridge sits between clients and server:
    Clients <-TCP/UDP-> Inbound Transports -> Bridge -> Outbound Transport <-UDP-> Server

    Inbound transports:
        - TCPInbound: Listens on TCP socket, accepts IRC clients
        - UDPInbound: Listens on UDP socket for UDP clients

    Outbound transport:
        - UDPOutbound: Sends to CSC server via UDP

    Bridge:
        - Maintains session mapping (client address -> server communication)
        - Routes messages bidirectionally
        - Handles session timeouts
        - Optional encryption and protocol normalization

Configuration:
    Reads config.json from working directory with defaults:
        - server_host: "127.0.0.1" (CSC server address)
        - server_port: 9525 (CSC server UDP port)
        - tcp_listen_host: "0.0.0.0" (TCP listener bind address)
        - tcp_listen_port: 9667 (TCP listener port for IRC clients)
        - udp_listen_host: "127.0.0.1" (UDP listener bind address)
        - udp_listen_port: 9526 (UDP listener port)
        - session_timeout: 300 (seconds before idle session cleanup)
        - encryption_enabled: false (optional encryption)
        - gateway_mode: null (optional protocol normalization)

Threading:
    Main thread blocks on threading.Event().wait() to keep daemon threads alive.
    All transport listeners and bridge logic run in daemon threads.
    Killing the process terminates all threads immediately.

Side Effects:
    - Changes process working directory (os.chdir)
    - Modifies sys.path globally
    - Configures logging globally (logging.basicConfig)
    - Opens network sockets (TCP and UDP listeners)
    - Blocks indefinitely in main thread

Usage:
    python main.py                # Run as script
    python -m csc_bridge.main     # Run as module
    systemctl start csc-bridge    # Run as systemd service

Exit Codes:
    - Never exits normally (runs until killed)
    - SIGTERM/SIGINT: Terminates daemon threads, process exits

Dependencies:
    - csc_bridge.bridge: Bridge class
    - csc_bridge.transports.tcp_inbound: TCPInbound transport
    - csc_bridge.transports.udp_inbound: UDPInbound transport
    - csc_bridge.transports.udp_outbound: UDPOutbound transport
"""

import sys
import os
import json
import logging

# Ensure CWD is the bridge directory for data files
_bridge_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_bridge_dir)

# Keep project root in path for services/ if needed
_parent = os.path.dirname(_bridge_dir)
if _parent not in sys.path:
    sys.path.append(_parent)

# Configure logging using the centralized Log class path logic
from csc_service.shared.log import Log
class BridgeLog(Log):
    def __init__(self):
        super().__init__()
        self.name = "Bridge"
        import os
        from pathlib import Path
        self.log_file = str(Path(self.log_file).parent / f"{self.name}.log")

_bridge_log = BridgeLog()
_log_file = _bridge_log.log_file

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(message)s',
    handlers=[
        logging.FileHandler(_log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def main():
    """Load configuration, create transports, start bridge, and block indefinitely.

    Args:
        None: Configuration is read from config.json in the working directory.

    Returns:
        None: Does not return; blocks indefinitely until process is killed.

    Raises:
        ImportError: If csc_bridge modules cannot be imported.
        json.JSONDecodeError: If config.json is malformed (falls back to defaults).
        OSError: If network sockets cannot be created (port in use, permission denied).
        Exception: Any exception from transport or bridge initialization propagates.

    Data:
        - Reads: config.json (optional, falls back to defaults if missing)
        - Writes: None
        - Mutates:
            - Creates transport instances (tcp_inbound, udp_inbound, outbound)
            - Creates bridge instance
            - Starts daemon threads for transports and bridge

    Side effects:
        - Logging: Bridge and transports log via logging module (INFO level)
        - Network I/O:
            - TCP listener binds to tcp_listen_host:tcp_listen_port (default 0.0.0.0:9667)
            - UDP listener binds to udp_listen_host:udp_listen_port (default 127.0.0.1:9526)
            - UDP outbound connects to server_host:server_port (default 127.0.0.1:9525)
        - Disk writes: None (logging may write to stdout/stderr)
        - Thread safety: Main thread blocks; all work done in daemon threads.
          threading.Event().wait() blocks main thread indefinitely.

    Children:
        - json.load(): Reads config.json
        - TCPInbound.__init__(): Creates TCP listener transport
        - UDPInbound.__init__(): Creates UDP listener transport
        - UDPOutbound.__init__(): Creates UDP outbound transport
        - Bridge.__init__(): Creates bridge instance with transports
        - Bridge.start(): Starts all daemon threads (listeners, session manager)
        - threading.Event().wait(): Blocks main thread indefinitely

    Parents:
        - __main__ block: Calls this when script is executed directly
        - systemd service: May call this as entry point for daemon

    Execution Flow:
        1. Load config.json (fall back to defaults if missing)
        2. Create TCPInbound transport with config params
        3. Create UDPInbound transport with config params
        4. Create UDPOutbound transport with server params
        5. Create Bridge with transports list and config options
        6. Call bridge.start() to launch daemon threads
        7. Block main thread on threading.Event().wait()
        8. Never returns; process must be killed (SIGTERM, SIGINT, SIGKILL)

    Configuration Options:
        - server_host (str): CSC server IP address (default: "127.0.0.1")
        - server_port (int): CSC server UDP port (default: 9525)
        - tcp_listen_host (str): TCP listener bind address (default: "0.0.0.0")
        - tcp_listen_port (int): TCP listener port (default: 9667)
        - udp_listen_host (str): UDP listener bind address (default: "127.0.0.1")
        - udp_listen_port (int): UDP listener port (default: 9526)
        - session_timeout (int): Session idle timeout in seconds (default: 300)
        - encryption_enabled (bool): Enable encryption (default: False)
        - gateway_mode (str|null): Protocol normalization mode (default: null)

    Session Management:
        Bridge maintains mapping of client addresses to server sessions.
        Inactive sessions are cleaned up after session_timeout seconds.
        Each inbound message creates/refreshes a session.
        Outbound messages are routed back to the correct client based on session.

    Daemon Behavior:
        All worker threads are daemon threads (daemon=True).
        Main thread must stay alive to keep daemon threads running.
        threading.Event().wait() blocks indefinitely with no timeout.
        Process termination (SIGTERM/SIGINT) kills all threads immediately.
    """
    from .bridge import Bridge
    from .transports.tcp_inbound import TCPInbound
    from .transports.udp_inbound import UDPInbound
    from .transports.udp_outbound import UDPOutbound
    from ..shared.subprocess_wrapper import patch_subprocess

    # Patch subprocess to auto-hide windows on Windows
    patch_subprocess()

    # Load configuration
    config_file = "config.json"
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"Config file {config_file} not found, using defaults")
        config = {
            "server_host": "127.0.0.1",
            "server_port": 9525,
            "tcp_listen_host": "0.0.0.0",
            "tcp_listen_port": 9667,
            "session_timeout": 300,
        }

    # Create transports
    tcp_inbound = TCPInbound(
        host=config.get("tcp_listen_host", "0.0.0.0"),
        port=config.get("tcp_listen_port", 9667)
    )
    tcp_tunnel_inbound = TCPInbound(
        host=config.get("tcp_tunnel_listen_host", "0.0.0.0"),
        port=config.get("tcp_tunnel_listen_port", 9666)
    )
    udp_inbound = UDPInbound(
        host=config.get("udp_listen_host", "127.0.0.1"),
        port=config.get("udp_listen_port", 9526)
    )
    outbound = UDPOutbound(
        server_host=config.get("server_host", "127.0.0.1"),
        server_port=config.get("server_port", 9525)
    )

    # Create and start bridge
    bridge = Bridge(
        inbound_transports=[tcp_inbound, tcp_tunnel_inbound, udp_inbound],
        outbound_transport=outbound,
        session_timeout=config.get("session_timeout", 300),
        encrypt=config.get("bridge_encryption_enabled", True),
        normalize_mode=config.get("gateway_mode", None),
    )

    bridge.start()

    # Keep the process running - background threads are daemon threads
    # so we need to block the main thread to keep them alive
    import threading
    threading.Event().wait()

if __name__ == "__main__":
    main()
