# Bridge Server Infrastructure Setup

This document describes the configuration and deployment of the CSC Bridge with multi-transport support and mandatory bridge-to-server encryption.

## Network Port Assignments

| Port | Protocol | Usage | Description |
|------|----------|-------|-------------|
| 9525 | UDP | Server | Main CSC IRC Server port |
| 9526 | UDP | Bridge Inbound | Native CSC UDP client transport |
| 9667 | TCP | Bridge Inbound | Standard IRC client transport |
| 9666 | TCP | Bridge Tunnel | Remote bridge-to-bridge tunneling transport |

## Encryption Configuration

### Bridge-to-Server Encryption
By default, the bridge initiates an encrypted session with the CSC server using:
- **DH Key Exchange**: RFC 3526 Group 14 (2048-bit MODP)
- **AES-256-GCM**: Authenticated encryption for all routed traffic

This is controlled by the `bridge_encryption_enabled` setting (default: `true`).

### Client-to-Bridge Encryption
Encryption for standard IRC clients is optional and controlled by the `encryption_enabled` setting (default: `false`).

## Deployment Instructions

1. **Configure the Bridge**:
   Edit `config.json` in the bridge directory:
   ```json
   {
     "server_host": "facingaddictionwithhope.com",
     "server_port": 9525,
     "tcp_tunnel_listen_port": 9666,
     "bridge_encryption_enabled": true
   }
   ```

2. **Start the Bridge**:
   ```bash
   csc-ctl restart bridge
   ```

3. **Verify Connectivity**:
   Check `Bridge.log` for successful initialization of all three transports and established encrypted sessions with the server.

## Troubleshooting

- **Connection Refused (9666)**: Ensure the firewall on the bridge machine allows inbound TCP traffic on port 9666.
- **Encryption Failure**: Verify that both the bridge and server have compatible encryption libraries installed (e.g., `cryptography`).
