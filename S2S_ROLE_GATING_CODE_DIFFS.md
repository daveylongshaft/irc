# S2S Role Gating - Code Diffs

## Diff 1: `_load_cert_config()` - Load s2s_role

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

**Lines:** 793-830

```diff
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
+            self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
             # Load s2s_password from config if not already set from environment
             if not self.s2s_password:
                 self.s2s_password = cfg.get("s2s_password", "")
             if self.s2s_cert_path:
                 self._log(f"Cert auth configured: {Path(self.s2s_cert_path).name}")
             if self.s2s_password:
                 self._log(f"S2S password configured")
             if self.s2s_peers:
                 self._log(f"S2S peers configured: {len(self.s2s_peers)}")
+            self._log(f"S2S role: {self.s2s_role}")
         except Exception as e:
             self._log(f"WARNING: Could not load cert config: {e}")
```

**Summary:**
- Line +820: Load `s2s_role` with default `'leaf'`
- Line +829: Log the loaded role

---

## Diff 2: `start_listener()` - Conditional peer linker

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

**Lines:** 849-873

```diff
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
-            self._start_peer_linker()
+            # Only initiate peer links if this server is a 'leaf' node
+            if self.s2s_role == 'leaf':
+                self._start_peer_linker()
             return True
         except Exception as e:
             self._log(f"Failed to start S2S listener: {e}")
             return False
```

**Summary:**
- Lines +872-874: Replace unconditional `_start_peer_linker()` call with conditional check
- Only calls `_start_peer_linker()` if `self.s2s_role == 'leaf'`

---

## Diff 3: `_start_peer_linker()` - Early return for hub

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

**Lines:** 875-881

```diff
     def _start_peer_linker(self):
         """Start a thread that periodically tries to link to configured S2S peers."""
+        if self.s2s_role == 'hub':
+            return
         if not self.s2s_peers:
             return
         self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
         self._peer_link_thread.start()
         self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")
```

**Summary:**
- Lines +878-879: Check `self.s2s_role` immediately after docstring
- Early return if role is 'hub' (defense-in-depth)
- Existing `if not self.s2s_peers` check remains unchanged

---

## Combined Diff View

```diff
packages/csc-server-core/csc_server_core/server_network.py

 # Around line 820
-            self.s2s_peers = cfg.get("s2s_peers", [])
+            self.s2s_peers = cfg.get("s2s_peers", [])
+            self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
             # Load s2s_password from config if not already set from environment
 
 # Around line 828
              if self.s2s_peers:
                  self._log(f"S2S peers configured: {len(self.s2s_peers)}")
+             self._log(f"S2S role: {self.s2s_role}")
         except Exception as e:
 
 # Around line 871
              self._listener_thread.start()
              self._log(f"S2S UDP listener started on port {self.s2s_port}")
-             self._start_peer_linker()
+             # Only initiate peer links if this server is a 'leaf' node
+             if self.s2s_role == 'leaf':
+                 self._start_peer_linker()
              return True
 
 # Around line 876
      def _start_peer_linker(self):
          """Start a thread that periodically tries to link to configured S2S peers."""
+         if self.s2s_role == 'hub':
+             return
          if not self.s2s_peers:
              return
```

---

## Before & After Behavior

### Before (Current)
```
All servers (hub or leaf):
├── Load s2s_config
├── Start listener ✓
└── Start peer linker (always, regardless of role) ✓

Issue: Hub servers attempt to link to peers (undesired)
```

### After (Proposed)
```
Hub Server:
├── Load s2s_config (s2s_role='hub')
├── Start listener ✓
├── Check s2s_role == 'leaf'? No
└── Skip peer linker ✓

Leaf Server:
├── Load s2s_config (s2s_role='leaf')
├── Start listener ✓
├── Check s2s_role == 'leaf'? Yes
└── Start peer linker ✓

Result: Each server behaves according to its role
```

---

## Testing the Changes

### Test 1: Hub Server
```bash
# csc-service.json
{
  "s2s_role": "hub",
  "s2s_peers": []
}

# Expected in logs:
# [S2S] S2S role: hub
# [S2S] S2S UDP listener started on port 6667
# [NOT shown] S2S peer linker started
```

### Test 2: Leaf Server
```bash
# csc-service.json
{
  "s2s_role": "leaf",
  "s2s_peers": [{"host": "hub.example.com", "port": 6667}]
}

# Expected in logs:
# [S2S] S2S role: leaf
# [S2S] S2S UDP listener started on port 6667
# [S2S] S2S peer linker started, will try to link to 1 peer(s)
```

### Test 3: Default (no s2s_role)
```bash
# csc-service.json
{
  "s2s_peers": []
}

# Expected in logs:
# [S2S] S2S role: leaf  (defaults to leaf)
```

---

## Impact Assessment

| Aspect | Impact | Notes |
|--------|--------|-------|
| **Hub Servers** | Added | New behavior: skip peer linker |
| **Leaf Servers** | Unchanged | Existing behavior maintained |
| **Default** | Safe | Defaults to 'leaf' (current behavior) |
| **Backward Compatible** | Yes | Fully compatible with existing configs |
| **Breaking Changes** | None | No changes required for existing deployments |

---

## Validation Checklist

- [ ] All three diffs applied in order
- [ ] File syntax is valid Python
- [ ] Indentation matches existing code (4 spaces)
- [ ] All `self.s2s_role` references use lowercase
- [ ] Default value is `'leaf'` (string)
- [ ] Both guard conditions present (start_listener + _start_peer_linker)
- [ ] Logging statements added for visibility
- [ ] No method signatures changed
- [ ] No imports needed

---
