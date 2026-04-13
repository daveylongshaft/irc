"""Tunnel manager for CSC Bridge - manages unlimited configurable tunnels."""

import threading
from typing import Dict, List, Optional
from .tunnel import TunnelConfig, TunnelEntry
from .transports.tcp_inbound import TCPInbound
from .transports.udp_inbound import UDPInbound


class TunnelManager:
    """Manages multiple independent tunnels with per-tunnel routing and crypto."""

    def __init__(self):
        self._tunnels: Dict[str, TunnelEntry] = {}
        self._lock = threading.Lock()
        self._bridge: Optional[object] = None  # Bridge instance, set via bind_bridge()

    def bind_bridge(self, bridge):
        """Bind the manager to a Bridge instance (called once from Bridge.__init__)."""
        self._bridge = bridge

    def add_tunnel(self, config: TunnelConfig) -> TunnelEntry:
        """Add a new tunnel, creating and starting its inbound listener.

        Raises ValueError if tunnel name already exists or port binding fails.
        """
        with self._lock:
            if config.name in self._tunnels:
                raise ValueError(f"Tunnel '{config.name}' already exists")

        # Create inbound transport
        try:
            if config.listen_proto == "tcp":
                inbound = TCPInbound(host=config.listen_host, port=config.listen_port)
            elif config.listen_proto == "udp":
                inbound = UDPInbound(host=config.listen_host, port=config.listen_port)
            else:
                raise ValueError(f"Unknown listen_proto: {config.listen_proto}")
        except OSError as e:
            raise ValueError(f"Cannot bind {config.listen_proto}:{config.listen_host}:{config.listen_port}: {e}")

        # Tag the transport so _create_session and TCPClientID use the tunnel name
        inbound._inbound_id = config.name

        # Create entry
        entry = TunnelEntry(config=config, inbound=inbound, inbound_id=config.name)

        # Register in bridge maps (before starting, so route_session can find it)
        with self._lock:
            self._bridge._inbound_map[config.name] = inbound
            self._bridge.inbound_transports.append(inbound)
            self._tunnels[config.name] = entry

        # Start the transport with callback to bridge's _on_client_data
        try:
            inbound.start(lambda data, cid, t=inbound: self._bridge._on_client_data(data, cid, t))
        except Exception as e:
            # Rollback on startup failure
            with self._lock:
                del self._tunnels[config.name]
                self._bridge.inbound_transports.remove(inbound)
                del self._bridge._inbound_map[config.name]
            inbound.stop()
            raise ValueError(f"Failed to start {config.name} listener: {e}")

        return entry

    def del_tunnel(self, name: str, drain: bool = False):
        """Remove a tunnel, stopping its listener and optionally destroying active sessions.

        If drain=False, actively destroy all sessions using this tunnel.
        If drain=True, just stop the listener and let sessions die naturally on timeout.

        Raises KeyError if tunnel not found.
        """
        with self._lock:
            entry = self._tunnels.pop(name)  # Raises KeyError if not found

        # Stop the inbound listener immediately (prevents new connections)
        entry.inbound.stop()

        # Remove from bridge maps
        with self._lock:
            self._bridge.inbound_transports.remove(entry.inbound)
            del self._bridge._inbound_map[name]

        # Destroy sessions using this tunnel (if not draining)
        if not drain:
            sessions_to_destroy = []
            with self._bridge._lock:
                for session in list(self._bridge._sessions.values()):
                    if session.inbound_name == name:
                        sessions_to_destroy.append(session)

            for session in sessions_to_destroy:
                self._bridge._destroy_session(session)

    def list_tunnels(self) -> List[dict]:
        """Return list of tunnel status dicts."""
        tunnels_list = []
        with self._lock:
            for entry in self._tunnels.values():
                # Count active sessions on this tunnel
                session_count = 0
                with self._bridge._lock:
                    for session in self._bridge._sessions.values():
                        if session.inbound_name == entry.config.name:
                            session_count += 1

                tunnels_list.append({
                    "name": entry.config.name,
                    "listen": f"{entry.config.listen_proto}:{entry.config.listen_host}:{entry.config.listen_port}",
                    "remote": f"{entry.config.remote_proto}:{entry.config.remote_host}:{entry.config.remote_port}",
                    "encrypt": entry.config.encrypt_mode,
                    "sessions": session_count,
                })
        return tunnels_list

    def route_session(self, inbound) -> Optional[TunnelEntry]:
        """Find the TunnelEntry that owns a given inbound transport (by object identity).

        O(n_tunnels) search - acceptable for small n.
        """
        with self._lock:
            for entry in self._tunnels.values():
                if entry.inbound is inbound:
                    return entry
        return None

    def reload_config(self, new_tunnel_dicts: List[dict]):
        """Reload tunnel configuration from a list of dicts.

        Adds new tunnels, removes old ones, updates changed ones.
        Diff is done on serialized config so crypto settings changes are detected.
        """
        # Parse new config
        new_configs = {}
        for d in new_tunnel_dicts:
            try:
                config = TunnelConfig.from_dict(d)
                new_configs[config.name] = config
            except ValueError as e:
                # Log but continue - don't fail entire reload for one bad config
                print(f"[TunnelManager] Skipping invalid tunnel config: {e}")

        # Get current tunnel names
        with self._lock:
            current_names = set(self._tunnels.keys())

        new_names = set(new_configs.keys())

        # Add new tunnels
        for name in new_names - current_names:
            try:
                self.add_tunnel(new_configs[name])
                print(f"[TunnelManager] Added tunnel '{name}'")
            except Exception as e:
                print(f"[TunnelManager] Failed to add tunnel '{name}': {e}")

        # Remove old tunnels
        for name in current_names - new_names:
            try:
                self.del_tunnel(name, drain=False)
                print(f"[TunnelManager] Removed tunnel '{name}'")
            except Exception as e:
                print(f"[TunnelManager] Failed to remove tunnel '{name}': {e}")

        # Update changed tunnels (remove old, add new)
        for name in new_names & current_names:
            with self._lock:
                old_config = self._tunnels[name].config
            new_config = new_configs[name]
            if old_config.to_dict() != new_config.to_dict():
                try:
                    self.del_tunnel(name, drain=False)
                    self.add_tunnel(new_config)
                    print(f"[TunnelManager] Updated tunnel '{name}'")
                except Exception as e:
                    print(f"[TunnelManager] Failed to update tunnel '{name}': {e}")
