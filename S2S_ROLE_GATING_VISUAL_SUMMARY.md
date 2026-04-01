# S2S Role Gating - Visual Code Changes

## Change 1: Initialize s2s_role in __init__

**File:** `packages/csc-server-core/csc_server_core/server_network.py`  
**Lines:** After 777 (after `self.s2s_peers = []`)

```
[BEFORE]
    774: self.s2s_cert_path = ""   # chain PEM (our cert + CA)
    775: self.s2s_key_path = ""    # our private key
    776: self.s2s_ca_path = ""     # CA cert for verifying peers
    777: self.s2s_peers = []       # List of {host, port} dicts for outbound connections
    778:
    779: debug_file = Path("/tmp/s2s_init_debug.log")

[AFTER]
    774: self.s2s_cert_path = ""   # chain PEM (our cert + CA)
    775: self.s2s_key_path = ""    # our private key
    776: self.s2s_ca_path = ""     # CA cert for verifying peers
    777: self.s2s_peers = []       # List of {host, port} dicts for outbound connections
    778:
    779: # S2S role: 'hub' (accepts inbound only) or 'leaf' (initiates outbound only)
    780: self.s2s_role = 'leaf'    # Default to leaf role
    781:
    782: debug_file = Path("/tmp/s2s_init_debug.log")
```

**Action:** INSERT 2 lines after line 777

---

## Change 2: Load s2s_role from config

**File:** `packages/csc-server-core/csc_server_core/server_network.py`  
**Lines:** 811-820 in _load_cert_config()

```
[BEFORE]
    811: self.s2s_cert_path = cfg.get("s2s_cert", "")
    812: self.s2s_key_path = cfg.get("s2s_key", "")
    813: self.s2s_ca_path = cfg.get("s2s_ca", "")
    814: self.s2s_peers = cfg.get("s2s_peers", [])
    815: # Load s2s_password from config if not already set from environment
    816: if not self.s2s_password:
    817:     self.s2s_password = cfg.get("s2s_password", "")

[AFTER]
    811: self.s2s_cert_path = cfg.get("s2s_cert", "")
    812: self.s2s_key_path = cfg.get("s2s_key", "")
    813: self.s2s_ca_path = cfg.get("s2s_ca", "")
    814: self.s2s_peers = cfg.get("s2s_peers", [])
    815: self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
    816: # Load s2s_password from config if not already set from environment
    817: if not self.s2s_password:
    818:     self.s2s_password = cfg.get("s2s_password", "")
```

**Action:** INSERT 1 line after line 814

---

## Change 3: Conditional peer linker in start_listener()

**File:** `packages/csc-server-core/csc_server_core/server_network.py`  
**Lines:** 869-870 in start_listener()

```
[BEFORE]
    865: self._listener_thread = threading.Thread(
    866:     target=self._receive_loop, daemon=True
    867: )
    868: self._listener_thread.start()
    869: self._log(f"S2S UDP listener started on port {self.s2s_port}")
    870: self._start_peer_linker()
    871: return True

[AFTER]
    865: self._listener_thread = threading.Thread(
    866:     target=self._receive_loop, daemon=True
    867: )
    868: self._listener_thread.start()
    869: self._log(f"S2S UDP listener started on port {self.s2s_port}")
    870: if self.s2s_role == 'leaf':
    871:     self._start_peer_linker()
    872: return True
```

**Action:** REPLACE line 870 with 2 lines (lines 870-871)

---

## Change 4: Early return in _start_peer_linker() for hub role

**File:** `packages/csc-server-core/csc_server_core/server_network.py`  
**Lines:** 875-881 in _start_peer_linker()

```
[BEFORE]
    875: def _start_peer_linker(self):
    876:     """Start a thread that periodically tries to link to configured S2S peers."""
    877:     if not self.s2s_peers:
    878:         return
    879:     self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
    880:     self._peer_link_thread.start()
    881:     self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")

[AFTER]
    875: def _start_peer_linker(self):
    876:     """Start a thread that periodically tries to link to configured S2S peers."""
    877:     # Hub role does not initiate outbound connections
    878:     if self.s2s_role == 'hub':
    879:         return
    880:     if not self.s2s_peers:
    881:         return
    882:     self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
    883:     self._peer_link_thread.start()
    884:     self._log(f"S2S peer linker started, will try to link to {len(self.s2s_peers)} peer(s)")
```

**Action:** INSERT 3 lines after line 876 (before the `if not self.s2s_peers` check)

---

## Behavior Matrix

| Config | start_listener() | _start_peer_linker() | Effect |
|--------|------------------|----------------------|--------|
| role='hub' | ✓ Runs | ✗ Early return | Hub mode: inbound only |
| role='leaf' (default) | ✓ Runs | ✓ Runs | Leaf mode: both |
| No role in config | ✓ Runs | ✓ Runs | Default to leaf (backward compatible) |
| No s2s config at all | ✗ Returns early | N/A | No S2S at all |

---

## csc-service.json Examples

### Hub Configuration
```json
{
  "s2s_cert": "/etc/csc/certs/hub-cert.pem",
  "s2s_key": "/etc/csc/certs/hub-key.pem",
  "s2s_ca": "/etc/csc/certs/ca.pem",
  "s2s_role": "hub",
  "s2s_peers": []
}
```

### Leaf Configuration (Default)
```json
{
  "s2s_cert": "/etc/csc/certs/leaf-cert.pem",
  "s2s_key": "/etc/csc/certs/leaf-key.pem",
  "s2s_ca": "/etc/csc/certs/ca.pem",
  "s2s_role": "leaf",
  "s2s_peers": [
    {"host": "hub.example.com", "port": 9520}
  ]
}
```

---

## Key Points

1. **Default is leaf role** - Maintains backward compatibility
2. **Both changes in _load_cert_config()** - Early return prevents peer linker execution
3. **Both changes in start_listener()** - Prevents peer linker from trying to connect
4. **Double protection** - Role checked at both method entry and caller
5. **No breaking changes** - Existing configs without `s2s_role` work as before
