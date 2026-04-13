"""Tunnel configuration and management for CSC Bridge."""

from dataclasses import dataclass
from typing import Optional
import base64


@dataclass
class TunnelConfig:
    """Configuration for a single bridge tunnel."""

    name: str
    listen_proto: str  # "tcp" or "udp"
    listen_host: str
    listen_port: int
    remote_proto: str  # "tcp" or "udp"
    remote_host: str
    remote_port: int
    encrypt_mode: str  # "none", "dh-aes", "psk-aes:<base64_key>"
    psk: Optional[bytes] = None  # Decoded PSK bytes, set if encrypt_mode starts with "psk-aes:"

    @classmethod
    def from_dict(cls, d: dict) -> "TunnelConfig":
        """Parse tunnel config from dict (config file format)."""
        name = d.get("name")
        if not name:
            raise ValueError("Tunnel config missing required 'name' field")

        listen_proto = d.get("listen_proto", "tcp")
        listen_host = d.get("listen_host", "0.0.0.0")
        listen_port = d.get("listen_port")
        if listen_port is None:
            raise ValueError(f"Tunnel '{name}' missing required 'listen_port'")

        remote_proto = d.get("remote_proto", "udp")
        remote_host = d.get("remote_host")
        if not remote_host:
            raise ValueError(f"Tunnel '{name}' missing required 'remote_host'")
        remote_port = d.get("remote_port")
        if remote_port is None:
            raise ValueError(f"Tunnel '{name}' missing required 'remote_port'")

        encrypt_mode = d.get("encrypt_mode", "none").strip()
        psk = None

        if encrypt_mode.startswith("psk-aes:"):
            psk_b64 = encrypt_mode.split(":", 1)[1]
            try:
                psk = base64.b64decode(psk_b64 + "==")  # Allow unpadded
            except Exception as e:
                raise ValueError(f"Tunnel '{name}' invalid PSK base64: {e}")

        return cls(
            name=name,
            listen_proto=listen_proto,
            listen_host=listen_host,
            listen_port=listen_port,
            remote_proto=remote_proto,
            remote_host=remote_host,
            remote_port=remote_port,
            encrypt_mode=encrypt_mode,
            psk=psk,
        )

    @classmethod
    def from_conn_str(cls, name: str, listen_str: str, remote_str: str, encrypt: str = "none") -> "TunnelConfig":
        """Parse tunnel config from partyline command format (proto:host:port)."""
        def parse_endpoint(endpoint_str: str, endpoint_name: str) -> tuple:
            parts = endpoint_str.rsplit(":", 1)
            if len(parts) != 2:
                raise ValueError(f"Invalid {endpoint_name}: expected proto:host:port, got {endpoint_str}")
            proto_host, port_str = parts
            proto_parts = proto_host.split(":", 1)
            if len(proto_parts) != 2:
                raise ValueError(f"Invalid {endpoint_name}: expected proto:host:port, got {endpoint_str}")
            proto, host = proto_parts
            try:
                port = int(port_str)
            except ValueError:
                raise ValueError(f"Invalid {endpoint_name} port: {port_str}")
            return proto, host, port

        listen_proto, listen_host, listen_port = parse_endpoint(listen_str, "listen endpoint")
        remote_proto, remote_host, remote_port = parse_endpoint(remote_str, "remote endpoint")

        return cls(
            name=name,
            listen_proto=listen_proto,
            listen_host=listen_host,
            listen_port=listen_port,
            remote_proto=remote_proto,
            remote_host=remote_host,
            remote_port=remote_port,
            encrypt_mode=encrypt,
            psk=None,  # from_conn_str doesn't decode PSK; partyline would use config file or separate mechanism
        )

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict (for config save/log)."""
        result = {
            "name": self.name,
            "listen_proto": self.listen_proto,
            "listen_host": self.listen_host,
            "listen_port": self.listen_port,
            "remote_proto": self.remote_proto,
            "remote_host": self.remote_host,
            "remote_port": self.remote_port,
            "encrypt_mode": self.encrypt_mode,
        }
        return result


@dataclass
class TunnelEntry:
    """Live tunnel instance with active inbound transport."""

    config: TunnelConfig
    inbound: object  # InboundTransport
    inbound_id: str  # = config.name, used as key in _inbound_map

    def make_outbound(self):
        """Create a fresh outbound transport for a new session."""
        from .transports.udp_outbound import UDPOutbound
        from .transports.tcp_outbound import TCPOutbound

        if self.config.remote_proto == "udp":
            return UDPOutbound(self.config.remote_host, self.config.remote_port)
        elif self.config.remote_proto == "tcp":
            return TCPOutbound(self.config.remote_host, self.config.remote_port)
        else:
            raise ValueError(f"Unknown remote_proto: {self.config.remote_proto}")
