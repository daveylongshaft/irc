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
from pathlib import Path

# Ensure CWD is the bridge directory for data files
_bridge_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_bridge_dir)

# Keep project root in path for services/ if needed
_parent = os.path.dirname(_bridge_dir)
if _parent not in sys.path:
    sys.path.append(_parent)

# Configure logging using the centralized Log class path logic
from csc_log import Log
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
    """Load configuration from etc/csc-service.json via Platform, create transports, start bridge.

    Configuration is loaded from the Platform data layer (etc/csc-service.json) which
    handles cross-platform path resolution (Windows, Linux, Mac, etc.).

    Args:
        None: Configuration is read from etc/csc-service.json via Platform.get_etc_dir().

    Returns:
        None: Does not return; blocks indefinitely until process is killed.

    Raises:
        ImportError: If csc_bridge modules cannot be imported.
        json.JSONDecodeError: If csc-service.json is malformed (falls back to defaults).
        OSError: If network sockets cannot be created (port in use, permission denied).
        Exception: Any exception from transport or bridge initialization propagates.

    Data:
        - Reads: etc/csc-service.json (via Platform.get_etc_dir())
        - Writes: None
        - Mutates:
            - Creates transport instances (tcp_inbound, tcp_tunnel_inbound, udp_inbound, outbound)
            - Creates bridge instance
            - Starts daemon threads for transports and bridge

    Execution Flow:
        1. Import Platform and get etc directory
        2. Load csc-service.json from etc/ (fall back to defaults if missing)
        3. Extract bridge configuration from json
        4. Create TCPInbound for local clients (local_tcp_port)
        5. Create TCPInbound for remote tunnel (remote_tcp_port → remote server)
        6. Create UDPInbound for UDP clients
        7. Create UDPOutbound for server communication
        8. Create Bridge with transports list and config options
        9. Call bridge.start() to launch daemon threads
        10. Block main thread on threading.Event().wait()
        11. Never returns; process must be killed (SIGTERM, SIGINT, SIGKILL)

    Configuration (from etc/csc-service.json "bridge" section):
        - server_host (str): CSC server IP address (default: "127.0.0.1")
        - server_port (int): CSC server UDP port (default: 9525)
        - local_tcp_port (int): Local TCP listener port (default: 9667)
        - remote_tcp_port (int): Remote/tunnel TCP listener port (default: 9666)
        - remote_host (str): Remote server host for tunnel (default: "haven")
        - session_timeout (int): Session idle timeout in seconds (default: 300)
        - encryption_enabled (bool): Enable encryption (default: False)
        - gateway_mode (str|null): Protocol normalization mode (default: null)
    """
    from .bridge import Bridge
    from .transports.tcp_inbound import TCPInbound
    from .transports.udp_inbound import UDPInbound
    from .transports.udp_outbound import UDPOutbound
    from csc_platform.subprocess_wrapper import patch_subprocess
    from csc_platform import Platform

    # Patch subprocess to auto-hide windows on Windows
    patch_subprocess()

    # Load configuration from etc/csc-service.json via Platform
    plat = Platform()
    config_file = plat.get_etc_dir() / "csc-service.json"

    # Fallback to csc-service.json in project root if etc doesn't have it
    if not config_file.exists():
        csc_root = os.environ.get('CSC_HOME') or os.environ.get('CSC_ROOT')
        if csc_root:
            config_file = Path(csc_root) / "csc-service.json"

    config = {}
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"WARNING: Failed to load {config_file}: {e}")
    else:
        print(f"No config file found at {config_file}, using defaults")

    # Extract bridge-specific configuration
    # Bridge config can be in top-level or under "bridge" key
    bridge_config = config.get("bridge", config)

    # Default server configuration
    server_host = config.get("server_host", "127.0.0.1")
    server_port = config.get("server_port", 9525)

    # Local bridge configuration (local_tcp_port -> server_host:server_port)
    local_tcp_host = bridge_config.get("local_tcp_host", "0.0.0.0")
    local_tcp_port = bridge_config.get("local_tcp_port", 9667)

    # Remote bridge configuration (remote_tcp_port -> remote_host:server_port)
    remote_tcp_host = bridge_config.get("remote_tcp_host", "0.0.0.0")
    remote_tcp_port = bridge_config.get("remote_tcp_port", 9666)
    remote_host = bridge_config.get("remote_host", "haven")

    # UDP listener configuration
    udp_host = bridge_config.get("local_udp_host", "127.0.0.1")
    udp_port = bridge_config.get("local_udp_port", 9526)

    # Other options
    session_timeout = config.get("session_timeout", 300)
    encryption_enabled = config.get("bridge_encryption_enabled", False)
    gateway_mode = config.get("gateway_mode", None)

    print(f"[Bridge] Config loaded from {config_file}")
    print(f"[Bridge] Local:  TCP {local_tcp_host}:{local_tcp_port} -> {server_host}:{server_port}")
    print(f"[Bridge] Remote: TCP {remote_tcp_host}:{remote_tcp_port} -> {remote_host}:{server_port}")
    print(f"[Bridge] UDP:    {udp_host}:{udp_port}")

    # Create transports
    # Local bridge: clients connect on local_tcp_port, forwards to local server
    tcp_inbound = TCPInbound(
        host=local_tcp_host,
        port=local_tcp_port
    )

    # Remote/tunnel bridge: clients connect on remote_tcp_port, forwards to remote server
    tcp_tunnel_inbound = TCPInbound(
        host=remote_tcp_host,
        port=remote_tcp_port
    )

    udp_inbound = UDPInbound(
        host=udp_host,
        port=udp_port
    )

    # Outbound transport for local server
    outbound = UDPOutbound(
        server_host=server_host,
        server_port=server_port
    )

    # Create and start bridge
    bridge = Bridge(
        inbound_transports=[tcp_inbound, tcp_tunnel_inbound, udp_inbound],
        outbound_transport=outbound,
        session_timeout=session_timeout,
        encrypt=encryption_enabled,
        normalize_mode=gateway_mode,
    )

    bridge.start()

    # Keep the process running - background threads are daemon threads
    # so we need to block the main thread to keep them alive
    # Also check for SHUTDOWN file to allow graceful termination
    import threading
    from pathlib import Path

    # Find project root for SHUTDOWN file
    csc_root = os.environ.get('CSC_HOME') or os.environ.get('CSC_ROOT')
    if not csc_root:
        csc_root = Path(__file__).resolve().parent
        for _ in range(10):
            if (csc_root / "SHUTDOWN").exists() or (csc_root / "csc-service.json").exists():
                break
            csc_root = csc_root.parent
            if csc_root == csc_root.parent:
                break

    shutdown_file = Path(csc_root) / "SHUTDOWN"
    stop_event = threading.Event()

    # Wait for shutdown signal or SHUTDOWN file
    while not stop_event.is_set():
        if shutdown_file.exists():
            print("[Bridge] SHUTDOWN file detected. Shutting down gracefully.")
            break
        stop_event.wait(timeout=1.0)  # Check every 1 second

    print("[Bridge] Exiting.")

if __name__ == "__main__":
    main()
