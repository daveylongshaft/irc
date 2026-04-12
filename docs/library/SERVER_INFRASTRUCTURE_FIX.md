# IRC Server Infrastructure - Complete Fix Plan

**Status:** CRITICAL - Core system non-functional
**Priority:** P0 - Blocks entire multi-AI collaboration vision
**Root Cause:** Missing dependencies, no pre-flight validation

---

## Problem Analysis

### What's Broken
```
Server Process: RUNNING (PID 295586)
Server Listening: NO (Listener thread stopped immediately)
Connection Possible: NO
Root Cause: Missing cryptography library
```

### Why This Matters
The IRC server is NOT infrastructure - it's the **CORE** of CSC:
- ✅ Central message hub for all AI agents
- ✅ Real-time collaboration channel
- ✅ System monitoring and coordination
- ✅ Agent-to-agent communication
- ✅ Human monitoring via Bridge

Without it working: **Multi-AI collaboration doesn't exist**

---

## Complete Fix (3 Parts)

### Part 1: Dependency Verification & Installation

**Required dependencies for server:**
```bash
# Core dependencies
pip install cryptography          # Encryption support
pip install anthropic             # Claude API
pip install google-generativeai   # Gemini API
pip install openai                # ChatGPT API

# Already should be installed (verify)
pip install pydantic
pip install pathlib
```

**Implementation:**
```python
# bin/verify-server-dependencies.py
#!/usr/bin/env python3
import sys

required = {
    "cryptography": "Encryption for IRC server",
    "anthropic": "Claude API client",
    "google.generativeai": "Gemini API client",
    "openai": "ChatGPT API client",
}

missing = []
for module, reason in required.items():
    try:
        __import__(module)
        print(f"✓ {module} - {reason}")
    except ImportError:
        print(f"✗ {module} - {reason} [MISSING]")
        missing.append(module)

if missing:
    print(f"\nMissing dependencies: {', '.join(missing)}")
    print(f"Fix: pip install {' '.join(missing)}")
    sys.exit(1)

print("\n✓ All server dependencies available")
```

### Part 2: Pre-Flight Validation

**Create server startup validator:**
```python
# packages/csc-service/csc_service/server/validator.py
import sys
from pathlib import Path

def validate_server_startup():
    """Validate server can start before spawning."""

    checks = [
        ("Dependencies", check_dependencies),
        ("Configuration", check_config),
        ("Storage", check_storage),
        ("Permissions", check_permissions),
    ]

    all_pass = True
    for name, check_func in checks:
        try:
            check_func()
            print(f"✓ {name} OK")
        except Exception as e:
            print(f"✗ {name} FAILED: {e}")
            all_pass = False

    return all_pass

def check_dependencies():
    """Verify cryptography, APIs available."""
    import cryptography
    import anthropic
    import google.generativeai
    import openai

def check_config():
    """Verify config files exist and are readable."""
    config_file = Path(__file__).parent / "config.json"
    if not config_file.exists():
        raise FileNotFoundError(f"Config not found: {config_file}")

def check_storage():
    """Verify storage directories writable."""
    storage_dir = Path("/c/csc/packages/csc-service/csc_service/server")
    test_file = storage_dir / ".validation_test"
    test_file.write_text("ok")
    test_file.unlink()

def check_permissions():
    """Verify can bind to port 9525."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("0.0.0.0", 9525))
        sock.close()
    except OSError:
        raise OSError("Cannot bind to port 9525 - already in use or permission denied")

if __name__ == "__main__":
    if not validate_server_startup():
        sys.exit(1)
    print("\n✓ Server ready to start")
```

### Part 3: Startup Script with Validation

**Create robust startup:**
```bash
#!/bin/bash
# bin/start-server.sh

set -e

echo "[SERVER] Pre-flight validation..."
python bin/verify-server-dependencies.py || {
    echo "[ERROR] Missing dependencies. Install with: pip install cryptography anthropic google-generativeai openai"
    exit 1
}

echo "[SERVER] Running startup checks..."
python -c "from csc_service.server.validator import validate_server_startup; validate_server_startup() or exit(1)"

echo "[SERVER] Starting IRC server on port 9525..."
python -m csc_service.server.main

echo "[SERVER] Server stopped"
```

---

## Integration Tests (What Should Catch This)

**Tests that SHOULD exist and fail immediately:**

```python
# tests/test_server_startup.py
import pytest
from pathlib import Path

def test_server_dependencies_installed():
    """MUST FAIL if cryptography missing."""
    import cryptography
    assert cryptography is not None

def test_server_can_import():
    """MUST FAIL if server module broken."""
    from csc_service.server import main
    assert main is not None

def test_server_can_bind_port():
    """MUST FAIL if port 9525 unavailable."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 9525))  # Will fail if can't bind
    sock.close()

def test_server_startup():
    """MUST FAIL if server crashes on startup."""
    from csc_service.server.validator import validate_server_startup
    assert validate_server_startup() == True
```

**Why these should run BEFORE anything else:**
- They validate the CORE infrastructure
- They prevent silent failures
- They ensure multi-AI collaboration is possible

---

## Bridge Validation (Secondary, But Important)

Bridge depends on Server, so:

```python
# tests/test_bridge_startup.py
def test_bridge_requires_server():
    """Bridge needs server running on 9525."""
    # Should fail gracefully if server not running
    from csc_service.bridge import bridge
    # Try to connect to server at localhost:9525
    # MUST fail with clear error if server down
```

---

## Monitoring & Heartbeat

**Add health check for Server:**

```python
# bin/check-server-health.sh
#!/bin/bash
PORT=9525
TIMEOUT=5

echo -n "Checking IRC server on port $PORT... "

if timeout $TIMEOUT bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$PORT" 2>/dev/null; then
    echo "✓ Server responding"
    exit 0
else
    echo "✗ Server not responding"
    echo "  Check: ps aux | grep csc-service"
    echo "  Check: tail -20 packages/csc-service/csc_service/server/Server.log"
    exit 1
fi
```

---

## Implementation Order

1. **IMMEDIATE (Now):**
   - Install missing dependencies
   - Create validator.py
   - Start server with validation
   - Test connection works

2. **SHORT TERM (Next cycle):**
   - Add integration tests (so it catches next time)
   - Create startup script with validation
   - Document server health checks

3. **ONGOING:**
   - Monitor server uptime
   - Validate agents can connect
   - Test Bridge can accept connections

---

## Success Criteria

- ✓ `netstat -an | grep 9525` shows LISTENING
- ✓ `nc -w 1 localhost 9525` connects successfully
- ✓ Server logs show "Server listening on ('0.0.0.0', 9525)" without immediate shutdown
- ✓ Bridge can connect to server
- ✓ Agents can connect as IRC clients
- ✓ All tests pass

---

## Why This Matters

The IRC server is not "nice to have infrastructure". It's the reason CSC exists:
- Multiple AI models collaborating
- Real-time monitoring
- Agent-to-agent communication
- Distributed coordination

Fixing it properly means:
1. **Tests catch it** - Next time a dependency breaks, we know immediately
2. **Validation prevents silent failures** - Server doesn't die in the background
3. **Monitoring ensures uptime** - We know the core is working
4. **Documentation prevents regression** - Future work knows what's critical
