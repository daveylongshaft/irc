# Claude Relay — Cross-Node AI Consultation

`claude-relay` is a mTLS-protected TCP daemon that lets any CSC node ask another
node's local Claude AI for help. It uses the same RSA certs already issued by the
CSC CA for S2S server links — no new infrastructure needed.

## How It Works

```
Windows node (haven-4346)                  Linux hub (haven-ef6e)
  claude-relay-ask 10.10.10.1 9531  ──mTLS──>  claude-relay :9531
  sends: "explain this error\x00"             runs: claude --print "explain..."
  receives: Claude's response                 returns: stdout
```

Both ends must present a cert signed by the CSC CA. Connections without a valid
cert are rejected at TLS handshake time.

## Protocol

1. Client connects over mTLS (presents its cert, verifies server cert against CA)
2. Client sends: `<prompt text>\x00` (prompt followed by a null byte as end marker)
3. Server runs: `claude --print "<prompt>"` with `CLAUDECODE` unset (allows nesting)
4. Server sends: response text, then closes connection

Null-byte framing is used instead of EOF signaling because `SHUT_WR` on an SSL
socket corrupts the TLS session state.

## Files

| File | Purpose |
|------|---------|
| `/opt/csc/bin/claude-relay` | Server daemon |
| `/opt/csc/bin/claude-relay-ask` | Client script |
| `~/.config/systemd/user/claude-relay.service` | Linux systemd unit |

## Cert Requirements

Server certs must have **both** `serverAuth` and `clientAuth` in Extended Key Usage.
EasyRSA type: `serverClient` (not the default `server` type).

To check an existing cert:
```bash
openssl x509 -in cert.pem -noout -text | grep -A2 "Extended Key"
```

Expected output:
```
X509v3 Extended Key Usage:
    TLS Web Server Authentication, TLS Web Client Authentication
```

To re-issue a cert with the correct type (requires CA access — Linux hub):
```bash
cd /opt/csc/etc/easy-rsa
./easyrsa --batch revoke <nodename>
openssl req -new -key /opt/csc/etc/<nodename>.key -subj "/CN=<nodename>" \
  -addext "subjectAltName=DNS:<nodename>" \
  -out pki/reqs/<nodename>.req
./easyrsa --batch sign-req serverClient <nodename>
cat pki/issued/<nodename>.crt pki/ca.crt > /opt/csc/etc/<nodename>.chain.pem
```

## Linux Hub Setup (haven-ef6e)

Already running. Systemd unit: `~/.config/systemd/user/claude-relay.service`

Port: **9531** on **0.0.0.0** (reachable from VPN subnet 10.10.10.0/24)

Cert used: `/opt/csc/etc/haven-ef6e.chain.pem` (re-issued with serverClient type)

```bash
systemctl --user status claude-relay
# Test locally:
echo "say hi" | CLAUDE_RELAY_CERT=... CLAUDE_RELAY_KEY=... CLAUDE_RELAY_CA=... \
  claude-relay-ask 127.0.0.1 9531
```

## Windows Node Setup (haven-4346)

See work order: `ops/wo/ready/claude-relay-setup-windows.md`

Short version:
1. Re-issue haven-4346 cert with `serverClient` type (CA is on Linux hub)
2. Copy `bin/claude-relay` and `bin/claude-relay-ask` to Windows
3. Create NSSM service pointing to Python and the relay script
4. Set environment: cert/key/CA paths + `CLAUDE_RELAY_PORT=9531`

## Asking Another Server's Claude for Help

```bash
# From Windows, ask the Linux hub's claude:
echo "what does this python traceback mean: ..." | claude-relay-ask 10.10.10.1 9531

# From Linux, ask Windows claude:
echo "is the csc-service running on windows?" | claude-relay-ask 10.10.10.2 9531

# claude-relay-ask reads cert paths from csc-service.json s2s_cert/key/ca
# or from CLAUDE_RELAY_CERT / CLAUDE_RELAY_KEY / CLAUDE_RELAY_CA env vars
```

## Security

- **Mutual TLS**: both client and server must present a CSC CA-signed cert
- **No cert, no connection**: rejected at TLS handshake before any data is read
- **Same CA as S2S links**: `easy-rsa/pki/ca.crt` — cert issuance requires CA key
- **VPN-only exposure**: relay binds to `0.0.0.0` but VPN subnet (10.10.10.0/24)
  is the intended path; public IP access still requires a valid cert
- **Nesting bypass**: `CLAUDECODE` env var is stripped before spawning claude

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_RELAY_PORT` | `9531` | TCP port to listen on |
| `CLAUDE_RELAY_HOST` | `0.0.0.0` | Bind address |
| `CLAUDE_RELAY_CERT` | — | Server cert chain PEM |
| `CLAUDE_RELAY_KEY` | — | Server private key PEM |
| `CLAUDE_RELAY_CA` | — | CA cert PEM (for client verification) |
