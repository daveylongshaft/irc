# S2S Role Gating Plan (Hub vs Leaf)

## Overview
Implement server role gating to control S2S peer linking behavior:
- **Hub** servers: Accept inbound S2S connections, do NOT initiate outbound peer links
- **Leaf** servers: Accept inbound S2S connections AND initiate outbound peer links
- Default: `'leaf'` (current behavior)

---

## Change 1: Load `s2s_role` in `_load_cert_config()`

**Location:** Lines 793-830 (method `_load_cert_config`)

**Current Code (Lines 806-823):**
```python
    def _load_cert_config(self):
        """Load S2S cert paths, password, and peers from csc-service.json (CSC_ROOT/csc-service.json)."""
        try:
            # Try CSC_HOME, then fall back to current directory
            csc_root = os.environ.get('CSC_HOME', '')
            if not csc_root:
                csc_root = os.getcwd()
            
            # DEBUG
            self._log(f"Loading config from {csc_root}/csc-service.json (CSC_HOME={os.environ.get('CSC_HOME', 'unset')}, CWD={os.getcwd()})")
            
            if not csc_root:
                return
            cfg_path = Path(csc_root) / "csc-service.json"
            if not cfg_path.exists():
                return
            import json as _json
            cfg = _json.loads(cfg_path.read_text())
            self.s2s_cert_path = cfg.get("s2s_cert", "")
            self.s2s_key_path = cfg.get("s2s_key", "")
            self.s2s_ca_path = cfg.get("s2s_ca", "")
            self.s2s_peers = cfg.get("s2s_peers", [])
            # Load s2s_password from config if not already set from environment
            if not self.s2s_password:
                self.s2s_password = cfg.get("s2s_password", "")
```

**Required Changes:**

1. **Add instance variable initialization** (before or after other `s2s_*` initializations):
   - Location: In `ServerNetwork.__init__()` (if it exists), or add after line 823
   - Add: `self.s2s_role = 'leaf'`  # Default

2. **Load `s2s_role` from config** (after line 822, in the `cfg.get()` calls):
   - Add after line 823:
   ```python
            self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
   ```

3. **Log the loaded role**:
   - Add after loading s2s_role:
   ```python
            self._log(f"S2S role: {self.s2s_role}")
   ```

**Updated Code Section:**
```python
            cfg = _json.loads(cfg_path.read_text())
            self.s2s_cert_path = cfg.get("s2s_cert", "")
            self.s2s_key_path = cfg.get("s2s_key", "")
            self.s2s_ca_path = cfg.get("s2s_ca", "")
            self.s2s_peers = cfg.get("s2s_peers", [])
            self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
            # Load s2s_password from config if not already set from environment
            if not self.s2s_password:
                self.s2s_password = cfg.get("s2s_password", "")
            if self.s2s_cert_path:
                self._log(f"Cert auth configured: {Path(self.s2s_cert_path).name}")
            if self.s2s_password:
                self._log(f"S2S password configured")
            if self.s2s_peers:
                self._log(f"S2S peers configured: {len(self.s2s_peers)}")
            self._log(f"S2S role: {self.s2s_role}")
```

---

## Change 2: Conditional peer linker in `start_listener()`

**Location:** Lines 849-873 (method `start_listener`)

**Current Code (Lines 860-873):**
```python
    def start_listener(self):
        """Start the UDP listener for inbound S2S connections with DH encryption."""
        print(f"[S2S] start_listener called. password={bool(self.s2s_password)}, cert={bool(self.s2s_cert_path)}, ca={bool(self.s2s_ca_path)}, peers={len(self.s2s_peers)}")

        if not self.s2s_password and not (self.s2s_cert_path and self.s2s_ca_path):
            print(f"[S2S] Listener disabled - no auth configured")
            self._log("No S2S password or certs configured, S2S listener disabled")
            return False

        try:
            self._listener_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._listener_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._listener_sock.bind(('0.0.0.0', self.s2s_port))
            self._listener_sock.settimeout(2)
            self._running = True
            self._listener_thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self._listener_thread.start()
            self._log(f"S2S UDP listener started on port {self.s2s_port}")
            self._start_peer_linker()
            return True
        except Exception as e:
            self._log(f"Failed to start S2S listener: {e}")
            return False
```

**Required Change:**

- **Line 872** (currently `self._start_peer_linker()`):
  - Replace with conditional check:
  ```python
            # Only initiate peer links if this server is a 'leaf' node
            if self.s2s_role == 'leaf':
                self._start_peer_linker()
  ```

**Updated Code Section:**
```python
            self._listener_thread.start()
            self._log(f"S2S UDP listener started on port {self.s2s_port}")
            # Only initiate peer links if this server is a 'leaf' node
            if self.s2s_role == 'leaf':
                self._start_peer_linker()
            return True
```

---

## Change 3: Early-return in `_start_peer_linker()`

**Location:** Lines 875-881 (method `_start_peer_linker`)

**Current Code (Lines 875-881):**
```python
    def _start_peer_linker(self):
        """Start a thread that periodically tries to link to configured S2S peers."""
        if not self.s2s_peers:
            return
        self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
        self._peer_link_thread.start()
        self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")
```

**Required Change:**

- **Add early-return at start** (after docstring, before line 876):
  - Add role check as first condition:
  ```python
        if self.s2s_role == 'hub':
            return
  ```

**Updated Code Section:**
```python
    def _start_peer_linker(self):
        """Start a thread that periodically tries to link to configured S2S peers."""
        if self.s2s_role == 'hub':
            return
        if not self.s2s_peers:
            return
        self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
        self._peer_link_thread.start()
        self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")
```

---

## Configuration File Structure

**File:** `csc-service.json` (in CSC_HOME or current directory)

**Example (hub server):**
```json
{
  "s2s_password": "shared-secret",
  "s2s_role": "hub",
  "s2s_cert": "/path/to/cert.pem",
  "s2s_key": "/path/to/key.pem",
  "s2s_ca": "/path/to/ca.pem",
  "s2s_peers": []
}
```

**Example (leaf server):**
```json
{
  "s2s_password": "shared-secret",
  "s2s_role": "leaf",
  "s2s_cert": "/path/to/cert.pem",
  "s2s_key": "/path/to/key.pem",
  "s2s_ca": "/path/to/ca.pem",
  "s2s_peers": [
    {"host": "hub.example.com", "port": 6667}
  ]
}
```

---

## Summary of Changes

| Change | Method | Lines | Action |
|--------|--------|-------|--------|
| 1a | `_load_cert_config()` | ~825 | Add `self.s2s_role = cfg.get("s2s_role", "leaf")` |
| 1b | `_load_cert_config()` | ~826 | Add log statement |
| 2 | `start_listener()` | 871-872 | Replace `self._start_peer_linker()` with conditional |
| 3 | `_start_peer_linker()` | ~877 | Add role check at start of method |

---

## Testing Strategy

1. **Hub server**: Should NOT initiate peer links (empty `s2s_peers` expected)
2. **Leaf server**: Should initiate peer links to configured peers
3. Both should accept inbound S2S connections
4. Default behavior (no `s2s_role` in config) should be 'leaf' (backward compatible)

---

## Backward Compatibility

- **Default role:** `'leaf'` maintains current behavior
- **No config file:** Defaults to `'leaf'` (safe)
- **No `s2s_role` key in config:** Defaults to `'leaf'` (safe)
- Existing deployments unaffected unless explicitly set to `'hub'`
