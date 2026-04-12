# mIRC Connection Setup for CSC Server

## Architecture

### Dual-Bridge Setup

```
Option 1 (Local):
  mIRC (unencrypted) → localhost:9667 → Bridge (encrypted) → localhost:9525

Option 2 (Remote):
  mIRC (unencrypted) → localhost:9666 → Bridge (encrypted) → facingaddictionwithhope.com:9525
```

## Connection Details

**Two Bridge Instances Available:**

| Option | mIRC Port | Destination | Purpose |
|--------|-----------|-------------|---------|
| Local | `localhost:9667` | `localhost:9525` (encrypted) | Test local server |
| Remote | `localhost:9666` | `facingaddictionwithhope.com:9525` (encrypted) | Connect to remote |

- **Encryption**: Bridge→Server (encrypted CSCS protocol)
- **Local**: mIRC→Bridge unencrypted (localhost only, no exposure)
- **Protocol**: IRC (RFC 2812) on input, CSCS on output
- **Status**: ✅ Both bridges running and tested

## mIRC Configuration

### Step 1: Add Servers
1. Open mIRC
2. Alt+O (or Tools → Options)
3. Connect → Servers
4. Click "Add"

**Server 1 (Local - Test Local Server)**:
   - **Description**: `CSC Local`
   - **IRC Server**: `localhost`
   - **Port(s)**: `9667`
   - **Group**: CSC

5. Click "Add" again for second server:

**Server 2 (Remote - Connect to Remote Server)**:
   - **Description**: `CSC Remote`
   - **IRC Server**: `localhost`
   - **Port(s)**: `9666`
   - **Group**: CSC

### Step 2: Configure Connection
1. Select the new server
2. Click "Select" to make it active
3. Under "Connect → Options":
   - **Nickname**: Pick a name (e.g., `davey` or `testclient`)
   - **Alternative**: Same name (or alt)
   - **Real name**: Your full name or description
   - **Email**: Leave blank or use test@localhost
   - **Username**: Keep default or use same as nickname

### Step 3: Advanced Settings (if needed)
- Most defaults are fine
- mIRC should handle both TCP and UDP (CSC uses UDP)
- If connection fails on TCP, try UDP-specific settings

## Connection Test

### Using mIRC
1. Double-click server in list to connect
2. Should see: `Welcome to csc-server Network`
3. Automatically join channels (if configured)

### Using Command Line (nc/netcat)
```bash
echo -e "NICK testclient\r\nUSER test 0 * :Test Client\r\nJOIN #general\r\n" | nc -u localhost 9525
```

## Default Channels

When connected, join these channels:
- `#general` - Main channel for test output and monitoring
- `#dev` - Development discussion
- `#logs` - System logs and diagnostics

### Join via mIRC
```
/join #general
/join #dev
/join #logs
```

## Testing Protocol

Once connected:
1. Type in `#general` to send messages to the channel
2. See server echo responses for command validation
3. Run test commands and observe results in real-time
4. Monitor agent activity as tests execute

## Troubleshooting

### Connection Fails
- Verify port 9525 is not blocked by firewall
- Check that csc-server is running: `netstat -ano | grep 9525`
- Try `localhost` instead of hostname if remote DNS fails

### Can't See Messages
- Ensure you've joined the channel: `/join #general`
- Check nickname is set: `/nick yournick`

### Server Unresponsive
- Check server process: `csc-ctl status`
- Restart: `csc-ctl restart csc-server` or `pkill csc-server && csc-server`
- Check logs: Look in `logs/` directory for error details

## Network Accessibility

### Local Testing
- Use `localhost:9525` or `127.0.0.1:9525`
- Works on same machine where server is running

### Remote Access
- Hostname `facingaddictionwithhope.com` should resolve to server machine
- Ensure port 9525 is forwarded on router (if behind NAT)
- Test DNS resolution: `ping facingaddictionwithhope.com`
- Test port access: `nc -u -zv facingaddictionwithhope.com 9525`

## Next Steps

1. ✅ Start server: `csc-server` (done)
2. ⏳ Connect mIRC client
3. ⏳ Join #general channel
4. ⏳ Run integration tests with real client
5. ⏳ Monitor test results in IRC channel

---

**Date**: 2026-02-28
**Server PID**: Check with `netstat -ano | grep 9525`
**Status**: Live and responding
