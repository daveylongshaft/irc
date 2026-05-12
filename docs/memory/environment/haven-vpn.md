---
slug: haven-vpn
name: Haven VPN
description: OpenVPN auto-connects to haven at 107.173.223.138 TCP/443 split-mode; tunnel IP 10.10.10.10.
type: environment
status: reference
tags: [environment, vpn, network, haven]
related: [server-topology]
updated: 2026-05-09T00:00:00Z
---

Haven server: 107.173.223.138 (public). VPN listeners: TCP/443 (active autostart), UDP/1194 (backup, not in autostart). Internal subnet 10.10.10.0/24; davey's laptop gets 10.10.10.10. Gateway pushed as 10.10.11.1 (cross-subnet; ping may be blocked but tunnel works for SSH/IRC/HTTP).

FAHU server (separate machine, do NOT confuse): 23.95.218.228, www.facingaddictionwithhope.com. Does NOT run OpenVPN even though the PKI CA cert CN says "facingaddictionwithhope.com" -- that is just PKI naming.

Active config on davey's laptop:
- File: C:\Program Files\OpenVPN\config-auto\haven4346.ovpn
- Service: OpenVPNService (Automatic startup)
- Mode: TCP/443 to 107.173.223.138, split-tunnel (pull-filter ignore "redirect-gateway"), topology subnet, keepalive 10 120

Verify tunnel: `ipconfig | findstr "OpenVPN"` should show 10.10.10.10 on the OpenVPN Data Channel Offload adapter. Log: C:\ProgramData\OpenVPN\Log\haven4346.log.
