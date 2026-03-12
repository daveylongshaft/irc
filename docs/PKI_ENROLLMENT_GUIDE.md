# CSC PKI Enrollment & Infrastructure Guide

This guide describes the TLS certificate enrollment system for the CSC ecosystem.

## 1. Core Architecture
The PKI system uses a central Certificate Authority (CA) to issue TLS certificates for secure Client-to-Server (C2S) and Server-to-Server (S2S) communication.

- **CA Host**: `facingaddictionwithhope.com` (Ubuntu/Apache)
- **Enrollment Endpoint**: `https://facingaddictionwithhope.com/csc/pki/`
- **Internal Port**: The `csc-service` on the CA host listens on `127.0.0.1:9530`.
- **Proxy**: Apache uses `irc/deploy/apache-pki.conf` to proxy external HTTPS requests to the local enrollment server.

## 2. Remote Server Setup (Ubuntu)
To enable enrollment on the central server:
1. Ensure `irc/deploy/apache-pki.conf` is symlinked to `/etc/apache2/conf-enabled/`.
2. Enable required modules: `a2enmod proxy proxy_http ssl rewrite`.
3. Reload Apache: `systemctl reload apache2`.
4. Enable PKI in `csc-service.json`: `"enable_pki": true`.
5. Restart `csc-service`.

## 3. Client Enrollment Process
To enroll a new node (like this Windows machine):
1. **Generate Token**: On the CA server (via IRC or CLI), generate a one-time enrollment token:
   `csc-ctl pki token <client_shortname>`
2. **Run Enrollment**: On the client machine, run:
   `csc-ctl enroll https://facingaddictionwithhope.com/csc/pki/ <token>`
3. **Verify**: Check the certificate status:
   `csc-ctl cert status`

## 4. Troubleshooting
- **404 Not Found**: Apache is up, but the PKI location block is not active or the symlink is missing.
- **503 Service Unavailable**: Apache proxy is working, but the `csc-service` enrollment thread is not running on port 9530.
- **Access Denied (Windows)**: If `csc-ctl status` crashes with an access violation, it is likely due to unstable network detection. Use the `SHUTDOWN` kill switch file in the project root to clear hung processes.

## 5. Deployment Files
- `irc/deploy/apache-pki.conf`: Apache configuration.
- `irc/packages/csc-service/csc_service/pki/`: Enrollment server implementation.
- `irc/packages/csc-service/csc_service/cli/commands/pki_cmd.py`: Client-side enrollment CLI.
