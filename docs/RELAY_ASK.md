Cross-Server Claude Relay & Transparent Logging
================================================

CSC supports cross-server AI consultation via encrypted mTLS relay with full
transaction logging and IRC channel broadcasting for complete transparency.

OVERVIEW
--------

One CSC server can ask another server's Claude instance a question without
needing direct API access. Perfect for:
- Distributed decision-making between servers
- Querying the other server's local context
- Load balancing heavy operations
- Audit trail of all cross-server AI interactions

All transactions are logged and broadcast to #relay-ask IRC channel for
transparency across all connected clients.

QUICK START
-----------

Ask another server's Claude:
  echo "what is the deployment status?" | claude-relay-ask 10.10.10.1 9531

Response is printed to stdout immediately.

Transaction is logged to logs/claude-relay-ask.log and broadcast to #relay-ask:
  [20260317 18:30:45] haven.4346 -> haven.ef6e
  [REQUEST]
  what is the deployment status?
  [RESPONSE]
  Status is healthy. All services running...

INFRASTRUCTURE
---------------

Two components:

1. claude-relay-ask (client)
   ========================
   Connects to remote server's relay listener (mTLS).
   Sends prompt, waits for response.
   Logs 2-way conversation.
   Location: bin/claude-relay-ask
   Usage: echo "prompt" | claude-relay-ask <host> [port]

2. claude-relay (server)
   ====================
   Listens on TCP port 9531 (mTLS).
   Receives prompts from authenticated clients.
   Runs `claude --print <prompt>` locally.
   Sends response back.
   Logs transaction.
   Location: bin/claude-relay
   Started by: csc-service daemon (auto)

MTLS SECURITY
--------------

Both client and server use the SAME S2S certificates:
  - CLAUDE_RELAY_CERT: /c/csc/etc/haven.XXXX.chain.pem
  - CLAUDE_RELAY_KEY: /c/csc/etc/haven.XXXX.key
  - CLAUDE_RELAY_CA: /c/csc/etc/ca.crt

No new certificates needed. Uses existing S2S PKI.

Client certificates must be signed by the CSC CA.
Server verifies client cert before accepting.

USAGE
-----

Direct CLI:
  # Ask another server's Claude
  echo "how many clients are online?" | claude-relay-ask haven.ef6e 9531

  # With explicit port
  echo "status report" | claude-relay-ask 10.10.10.1 9531

  # From a script
  RESPONSE=$(echo "check backups" | claude-relay-ask haven.ef6e 9531)
  echo "Claude says: $RESPONSE"

IRC Commands (if connected):
  # See all recent transactions
  /join #relay-ask

  # RelayBot broadcasts all new transactions to the channel
  # No manual interaction needed

Configuration:
  - Relaying is always available on port 9531
  - Client IP shows who asked the question
  - BotServ automatically monitors logs/claude-relay-ask.log
  - New entries broadcast to #relay-ask within 2 seconds

LOGGING
-------

Every transaction is logged to logs/claude-relay-ask.log with:

Format:
  ================================================================================
  [YYYY-MM-DD HH:MM:SS] local_hostname -> remote_hostname
  ================================================================================

  [REQUEST]
  <full prompt text>

  [RESPONSE]
  <full response text>

Example:
  ================================================================================
  [2026-03-17 18:30:45] haven.4346 -> haven.ef6e
  ================================================================================

  [REQUEST]
  Are the backups running correctly?

  [RESPONSE]
  Yes, backups are running. Last backup: 2026-03-17 12:00:00.
  Backup size: 2.3 GB. All systems nominal.

Log entries include:
  - Timestamp (ISO 8601 format)
  - Source (asking server hostname)
  - Destination (answering server hostname)
  - Full request text
  - Full response text (including errors if any)

Log file location: logs/claude-relay-ask.log
Log is NOT git-tracked (in .gitignore)
Log persists across restarts for audit trail

TRANSPARENT BROADCASTS
----------------------

BotServ automatically monitors logs/claude-relay-ask.log and broadcasts
new transactions to #relay-ask IRC channel.

Broadcast format:
  RelayBot: [claude-relay-ask.log] [2026-03-17 18:30:45] haven.4346 -> haven.ef6e

Each transaction line appears immediately in #relay-ask when logged.

Clients see:
  RelayBot: [claude-relay-ask.log] [REQUEST]
  RelayBot: [claude-relay-ask.log] Are the backups running correctly?
  RelayBot: [claude-relay-ask.log] [RESPONSE]
  RelayBot: [claude-relay-ask.log] Yes, backups are running. Last backup...

Complete transparency: All relay asks are visible to all connected clients.

CONFIGURATION
--------------

Setup (automatic on first install):
  bin/setup-relay-ask-botserv

  This script:
  1. Creates #relay-ask channel in botserv.json
  2. Registers RelayBot for the channel
  3. Configures log monitoring
  4. Sets up broadcast_mode

Manually enable/disable in IRC:
  BOTSERV SETLOG RelayBot #relay-ask /path/to/logs/claude-relay-ask.log enable
  BOTSERV SETLOG RelayBot #relay-ask /path/to/logs/claude-relay-ask.log disable

Check current config:
  cat etc/botserv.json | grep -A 15 "relay-ask"

PERFORMANCE & LIMITS
--------------------

Response timeout: 300 seconds (5 minutes)
  - If Claude takes longer, connection times out
  - Error returned to client

Prompt size: Unlimited (within socket buffer)
  - Most prompts << 1KB
  - Large prompts (~100KB) work fine

Response size: Unlimited (streamed in 4KB chunks)
  - Large responses (multi-page) handled correctly
  - No truncation

Network latency: Included in 300s timeout
  - 100ms latency is negligible
  - Even 1s network lag is fine

MONITORING & DEBUGGING
----------------------

Check if relay is running:
  ps aux | grep "claude-relay"
  # Should show: python3 /path/to/bin/claude-relay

View relay log:
  tail -f logs/claude-relay-ask.log

Watch #relay-ask channel:
  /join #relay-ask
  # See all cross-server interactions in real time

Test from local machine:
  echo "test" | claude-relay-ask 127.0.0.1 9531

Test from remote:
  ssh haven.ef6e 'echo "test" | claude-relay-ask 10.10.10.1 9531'

Check relay port is open:
  netstat -tlnp | grep 9531
  # Should show: LISTEN on 0.0.0.0:9531

TROUBLESHOOTING
---------------

No response / connection timeout:
  - Check remote server is running: ps aux | grep csc-service
  - Check port 9531 is open: netstat -tlnp | grep 9531
  - Check firewall: ping <remote-host>
  - Check certs are valid: ls -la etc/*.pem

TLS handshake failed:
  - Verify cert paths in csc-service.json
  - Check CSC CA signed both server and client certs
  - Verify s2s_cert, s2s_key, s2s_ca exist and are readable

Certificate issues:
  - Run: csc-ctl enroll https://facingaddictionwithhope.com/csc/pki/
  - Or copy certs from other server: scp haven.ef6e:etc/*.pem ./etc/

Empty response:
  - Check Claude API key is set: echo $ANTHROPIC_API_KEY
  - Check claude CLI works: echo "test" | claude --print
  - Check remote server logs: tail logs/log.log

SECURITY NOTES
--------------

Prompts are encrypted in transit (mTLS).
Responses are encrypted in transit (mTLS).
Log file is plaintext (store securely).

Certificate validation:
  - Client cert must be signed by CSC CA
  - Server cert must be signed by CSC CA
  - Both verified before any data exchange

Network boundaries:
  - By default listens on 0.0.0.0 (all interfaces)
  - Use firewall to restrict access to trusted nodes only
  - Or set CLAUDE_RELAY_HOST=127.0.0.1 for localhost only

API keys:
  - Only local server can run claude --print
  - API key never transmitted over relay
  - Remote server cannot access your Claude API key

AUDIT & COMPLIANCE
------------------

All transactions are logged for audit trail:
  - Timestamp of each ask
  - Which server asked (source hostname)
  - Which server answered (dest hostname)
  - Complete request and response text

Logs are broadcast to IRC for organizational visibility:
  - All connected clients see all transactions
  - No hidden cross-server interactions
  - Transparent operation

Log retention:
  - logs/claude-relay-ask.log grows indefinitely
  - Manually rotate if needed: mv logs/claude-relay-ask.log logs/relay-ask-YYYY-MM-DD.log
  - Old logs are kept in logs/ directory

ARCHITECTURE
------------

Port allocation:
  9520 - S2S inter-server link (UDP)
  9525 - IRC server (UDP)
  9531 - Claude relay (TCP+TLS) [this feature]

Process flow:
  1. Client: echo "prompt" | claude-relay-ask <host> 9531
  2. Client: Connect via mTLS, verify server cert
  3. Server: Accept connection, verify client cert
  4. Server: recv_prompt() reads until null byte
  5. Server: subprocess.run(["claude", "--print", prompt])
  6. Server: Send response back via TLS
  7. Server: log_transaction(client, prompt, response)
  8. BotServ: Monitor logs/claude-relay-ask.log every 2 seconds
  9. BotServ: Broadcast new lines to #relay-ask
  10. Client: Receive response, print to stdout, exit
  11. Client: log_transaction(local, remote, prompt, response)

Both client and server log independently for redundancy.

EXAMPLES
--------

Example 1: Simple status check
  $ echo "what services are running?" | claude-relay-ask haven.ef6e
  Services running:
  - IRC server on UDP 9525
  - Queue worker (polling every 60s)
  - Test runner (polling every 60s)
  - PM (project manager)
  [OK]

Example 2: With explicit port
  $ echo "list online clients" | claude-relay-ask 10.10.10.1 9531
  Online clients:
  - alice (127.0.0.1:5000)
  - bob (192.168.1.1:5001)
  [OK]

Example 3: From a shell script
  $ ANSWER=$(echo "backup status?" | claude-relay-ask haven.ef6e 9531)
  $ if echo "$ANSWER" | grep -q "complete"; then
  >   echo "Backup OK, proceeding..."
  > else
  >   echo "Backup failed: $ANSWER"
  > fi

Example 4: Check in #relay-ask channel
  <user> /join #relay-ask
  <RelayBot> [claude-relay-ask.log] [2026-03-17 18:30:45] haven.4346 -> haven.ef6e
  <RelayBot> [claude-relay-ask.log] [REQUEST]
  <RelayBot> [claude-relay-ask.log] what services are running?
  <RelayBot> [claude-relay-ask.log] [RESPONSE]
  <RelayBot> [claude-relay-ask.log] Services running: IRC server, Queue worker...

REFERENCES
----------

Files:
  bin/claude-relay - Server (listener)
  bin/claude-relay-ask - Client (requester)
  bin/setup-relay-ask-botserv - Configuration script
  logs/claude-relay-ask.log - Transaction log
  etc/botserv.json - BotServ config with #relay-ask

See also:
  - CLAUDE.md - Cross-server relay reference
  - S2S SERVER LINKING in memory/MEMORY.md
  - mTLS certificate setup in PKI_ENROLLMENT_GUIDE.md
