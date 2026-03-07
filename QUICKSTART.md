# CSC Server + mIRC Quick Start

## Current Status
✅ **Server running**: localhost:9525 (UDP)
✅ **Bridge running**: localhost:6667 (TCP)
✅ **Tested**: Full connection chain verified

## Start Everything

### Option 1: Dual Bridges + Server (Recommended)
```bash
bin/start-bridges.bat
```
This starts:
1. CSC Server (localhost:9525)
2. Bridge 1: Local (irc://localhost:9667 → cscs://localhost:9525)
3. Bridge 2: Remote (irc://localhost:9666 → cscs://facingaddictionwithhope.com:9525)

### Option 2: Single Bridge + Server
```bash
bin/start-csc-full.bat
```
This starts:
1. CSC Server (localhost:9525)
2. Single Bridge (irc://localhost:6667 → cscs://localhost:9525)

### Option 3: Manual Start (Three Terminals)

**Terminal 1: Start Server**
```bash
cd /c/csc
source .env
csc-server
```
Expected output:
```
Server started
Listening on UDP port 9525
```

**Terminal 2: Start Bridge**
```bash
cd /c/csc
source .env
csc-bridge
```
Expected output:
```
[csc_bridge] Inbound transport started: TCPInbound
[csc_bridge] Inbound transport started: UDPInbound
[csc_bridge] Bridge started
```

## Connect with mIRC

### Step 1: Open mIRC
1. Launch mIRC
2. Alt+O (Options)
3. Connect → Servers
4. Click "Add"

### Step 2: Configure Server
- **Description**: `CSC Local`
- **IRC Server**: `localhost`
- **Port**: `6667`
- **Select this server and click "Select"**

### Step 3: Connect
- Click "Connect"
- mIRC should connect to localhost:6667 (Bridge)
- You'll see: `:csc-server 001 <yournick> :Welcome to csc-server Network`

### Step 4: Join Channels
Once connected, type in mIRC:
```
/join #general
/join #dev
/join #logs
```

## Using the IRC Server

### Send Messages
Type in any channel to broadcast:
```
#general > hello everyone
```

### Run Commands
In mIRC, commands start with `/`:
```
/nick newnickname      # Change your nick
/join #channelname     # Join a channel
/part #channelname     # Leave a channel
/quit goodbye message  # Disconnect
```

### Monitor Tests
When tests run:
1. They output results to `#general` channel
2. Watch the channel in real-time
3. See actual IRC protocol behavior, not just unit test assertions

## Architecture

```
┌─────────────┐
│   mIRC      │
│ (Unencrypted)
│ localhost:6667
└──────┬──────┘
       │ TCP
       ↓
┌──────────────┐
│   Bridge     │ (Encrypted tunnel option)
│ Translate/Proxy
└──────┬──────┘
       │
       ↓ UDP
┌──────────────┐
│   Server     │
│ localhost:9525
│ IRC Protocol
└──────────────┘
```

## Key Points

- **No encryption between mIRC and Bridge** (local only - localhost)
- **Bridge can enable encryption** to Server later in config
- **Data never sent in plaintext** over internet (stays local until Bridge)
- **Real integration testing**: Actual IRC client → Protocol validation
- **Not just unit tests**: Can connect with real client and verify behavior

## Troubleshooting

### mIRC Can't Connect
1. Verify server and bridge are running:
   ```bash
   netstat -ano | grep -E "6667|9525"
   ```
2. Check Bridge.log for errors:
   ```bash
   tail -50 Bridge.log
   ```
3. Try connection test:
   ```bash
   python -c "import socket; s=socket.socket(); s.connect(('127.0.0.1', 6667)); print('OK')"
   ```

### Server Not Responding
1. Check Server.log
2. Verify csc-server process is running
3. Check port 9525 is listening (UDP)

### Can't See Test Results
1. Ensure you've joined #general: `/join #general`
2. Check that tests are actually running: `csc-ctl status`
3. Look in logs/ directory for recent test output

## Next Steps

1. ✅ Connect with mIRC
2. ✅ Join #general
3. ⏳ Run tests through queue-worker
4. ⏳ Watch results appear in IRC
5. ⏳ Verify actual protocol behavior with real client

---

**Date**: 2026-02-28
**Status**: Ready for mIRC connection and real integration testing
