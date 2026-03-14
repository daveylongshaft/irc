# Bridge Connectivity & Encryption Test

## Overview

The `test_0000_verify_client_bridge_localserver_service_commands.py` script provides comprehensive end-to-end integration testing of the CSC client, bridge, local server, and service command execution.

## What Tests Are Provided

### 1. **Bridge Connectivity Test**
- Verifies TCP connection to bridge on 127.0.0.1:9666
- Confirms bridge can forward messages to server (9525)
- Validates bidirectional communication
- ✅ **Status**: Basic handshake and message flow

### 2. **Encryption Auto-Detection Test**
- Monitors protocol stream for `CRYPTOINIT` messages (Diffie-Hellman initiation)
- Detects `CRYPTOINIT DHREPLY` (server's DH response)
- Confirms AES key negotiation completed
- ✅ **Status**: Bridge automatically enables encryption when configured
- **Config File**: `packages/csc-service/csc_service/bridge/config.json` has `"encryption_enabled": true`

### 3. **Command Execution Test**
- Sends: `ai do builtin list_dir .`
- Waits for response with 'do' token
- Verifies command execution through encrypted bridge
- Demonstrates end-to-end command routing
- ✅ **Status**: Commands executed and responses received

### 4. **Graceful Shutdown Test**
- Issues: `quit` command
- Verifies server cleanup without timeout
- Confirms proper session teardown
- ✅ **Status**: Clean disconnection

## Running the Test

### Prerequisites
- Server running on 127.0.0.1:9525
- Bridge running on 127.0.0.1:9666
- Both with encryption enabled

### Quick Start
```bash
# On the server machine:
csc-ctl install server        # Install server as background service
csc-ctl restart server         # (or start manually)

# On client machine (or same machine):
python test_0000_verify_client_bridge_localserver_service_commands.py
```

Or let the test runner auto-execute:
```bash
# Test runner will auto-run when log is missing:
# tests/logs/test_0000_verify_client_bridge_localserver_service_commands.log
```

### Expected Output
```
[TEST] Connecting to server through bridge...
[TEST] Bridge encryption: ENABLED (auto-detect)

[TEST 1] Bridge Connectivity
✓ Bridge connected successfully

[TEST 2] Encryption Auto-Detection
✓ CRYPTOINIT handshake detected
  → Bridge sent CRYPTOINIT (DH key exchange)
  → Server replied with CRYPTOINIT DHREPLY
  → Encryption auto-detected and negotiated

[TEST 3] Command Execution
✓ Response received with 'do' token
  → Command executed through encrypted bridge

[TEST 4] Graceful Shutdown
✓ QUIT command issued successfully
  → Server cleanup completed without timeout

[SUMMARY]
Bridge Connectivity:    ✓ PASS
Encryption Auto-Detect: ✓ PASS
Command Execution:      ✓ PASS
Graceful Shutdown:      ✓ PASS

🎉 All tests passed!
```

## Encryption Details

### How Encryption Works

1. **Auto-Detection**: Bridge detects server supports encryption (from config)
2. **Key Exchange**:
   - Bridge sends: `CRYPTOINIT <dh_params>`
   - Server sends: `CRYPTOINIT DHREPLY <server_dh_params>`
3. **AES Encryption**: Both sides compute shared secret → AES-256 key
4. **Message Flow**:
   - Client → Bridge: plaintext
   - Bridge → Server: encrypted with AES
   - Server → Bridge: encrypted with AES
   - Bridge → Client: plaintext (decrypted)

### Configuration

**Bridge**: `packages/csc-service/csc_service/bridge/config.json`
```json
{
  "server_host": "facingaddictionwithhope.com",
  "encryption_enabled": true,
  ...
}
```

**Server**: Encryption supported via `crypto.py` (DHExchange + AES)

## Test Results Interpretation

| Test | Pass | Inconclusive | Fail |
|------|------|--------------|------|
| **Bridge Connectivity** | Response received | Delayed response | No response |
| **Encryption** | CRYPTOINIT + DHREPLY | One message only | Neither found |
| **Command Execution** | 'do' token in output | Response but no token | No output |
| **Shutdown** | QUIT issued | Implicit close | Timeout |

## Troubleshooting

### "No response from bridge"
- Check bridge is running: `ps aux | grep bridge`
- Check port 9666 is listening: `netstat -tlnp | grep 9666`
- Check bridge log: `tail logs/Bridge.log`

### "No CRYPTOINIT handshake"
- Verify `encryption_enabled: true` in bridge config
- Check server supports encryption (it does by default)
- May need to wait longer for first message

### "Command didn't execute"
- Check server is actually running: `ps aux | grep server`
- Verify builtin service available: `ai builtin list`
- Check server log for errors: `tail logs/Server.log`

### "QUIT failed"
- Server may have already closed connection
- Check for timeout messages in output
- This is normal if server unresponsive

## Next Steps

To run this test on **Fahu**:

1. Pull latest code
2. Run: `csc-ctl install server`
3. From any client machine: `python test_bridge_connection.py`

The test will verify the encrypted bridge connection to fahu works correctly.
