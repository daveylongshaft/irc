# S2S Role Gating - Implementation Guide

## Quick Summary

Implement hub vs leaf role gating by:
1. Loading `s2s_role` from csc-service.json config (default: `'leaf'`)
2. Conditionally calling `_start_peer_linker()` only for leaf servers
3. Early-returning from `_start_peer_linker()` if hub

---

## Detailed Implementation

### Step 1: Initialize `s2s_role` in `_load_cert_config()`

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

**Method:** `_load_cert_config()` (Lines ~793-830)

**Exact Location to Modify:**

Find this block (around line 819-822):
```python
            self.s2s_peers = cfg.get("s2s_peers", [])
            # Load s2s_password from config if not already set from environment
            if not self.s2s_password:
                self.s2s_password = cfg.get("s2s_password", "")
```

**Replace with:**
```python
            self.s2s_peers = cfg.get("s2s_peers", [])
            self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
            # Load s2s_password from config if not already set from environment
            if not self.s2s_password:
                self.s2s_password = cfg.get("s2s_password", "")
```

**Add logging** (after existing s2s config logs, around line 828):

Find this block:
```python
            if self.s2s_peers:
                self._log(f"S2S peers configured: {len(self.s2s_peers)}")
        except Exception as e:
```

**Add before the except:**
```python
            if self.s2s_peers:
                self._log(f"S2S peers configured: {len(self.s2s_peers)}")
            self._log(f"S2S role: {self.s2s_role}")
        except Exception as e:
```

**Code Snippet to Add:**
```python
self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'
```

**Log Statement to Add:**
```python
self._log(f"S2S role: {self.s2s_role}")
```

---

### Step 2: Conditional Peer Linker in `start_listener()`

**Method:** `start_listener()` (Lines ~849-873)

**Exact Location to Modify:**

Find this line (around line 872):
```python
            self._log(f"S2S UDP listener started on port {self.s2s_port}")
            self._start_peer_linker()
            return True
```

**Replace with:**
```python
            self._log(f"S2S UDP listener started on port {self.s2s_port}")
            # Only initiate peer links if this server is a 'leaf' node
            if self.s2s_role == 'leaf':
                self._start_peer_linker()
            return True
```

**Code Snippet to Replace:**
```python
            self._start_peer_linker()
```

**With:**
```python
            # Only initiate peer links if this server is a 'leaf' node
            if self.s2s_role == 'leaf':
                self._start_peer_linker()
```

---

### Step 3: Early Return in `_start_peer_linker()`

**Method:** `_start_peer_linker()` (Lines ~875-881)

**Exact Location to Modify:**

Find this method:
```python
    def _start_peer_linker(self):
        """Start a thread that periodically tries to link to configured S2S peers."""
        if not self.s2s_peers:
```

**Replace with:**
```python
    def _start_peer_linker(self):
        """Start a thread that periodically tries to link to configured S2S peers."""
        if self.s2s_role == 'hub':
            return
        if not self.s2s_peers:
```

**Code Snippet to Add (after docstring):**
```python
        if self.s2s_role == 'hub':
            return
```

---

## Testing Checklist

### Configuration Files

#### Hub Server Config
Create `csc-service.json` with:
```json
{
  "s2s_password": "test-password",
  "s2s_role": "hub",
  "s2s_cert": "/etc/csc/hub-cert.pem",
  "s2s_key": "/etc/csc/hub-key.pem",
  "s2s_ca": "/etc/csc/ca-cert.pem",
  "s2s_peers": []
}
```

#### Leaf Server Config
Create `csc-service.json` with:
```json
{
  "s2s_password": "test-password",
  "s2s_role": "leaf",
  "s2s_cert": "/etc/csc/leaf-cert.pem",
  "s2s_key": "/etc/csc/leaf-key.pem",
  "s2s_ca": "/etc/csc/ca-cert.pem",
  "s2s_peers": [
    {"host": "hub.example.com", "port": 6667}
  ]
}
```

### Test Cases

1. **Hub Server Startup**
   - [ ] Server starts successfully
   - [ ] Log shows `S2S role: hub`
   - [ ] No peer linker thread starts
   - [ ] Log does NOT show "S2S peer linker started"
   - [ ] Server accepts inbound S2S connections

2. **Leaf Server Startup**
   - [ ] Server starts successfully
   - [ ] Log shows `S2S role: leaf`
   - [ ] Peer linker thread starts (if peers configured)
   - [ ] Log shows "S2S peer linker started, will try to link to X peer(s)"
   - [ ] Server attempts to connect to peers
   - [ ] Server accepts inbound S2S connections

3. **Default Behavior (no s2s_role in config)**
   - [ ] Server defaults to `leaf`
   - [ ] Log shows `S2S role: leaf`
   - [ ] Peer linker behavior as expected for leaf

4. **Invalid Role**
   - [ ] If `s2s_role: "invalid"`, server still loads it as-is
   - [ ] Only 'hub' triggers early return (safe default)
   - [ ] Server logs the role for debugging

---

## Log Output Examples

### Hub Server
```
[S2S] start_listener called. password=True, cert=True, ca=True, peers=0
[S2S] S2S UDP listener started on port 6667
S2S role: hub
```

### Leaf Server
```
[S2S] start_listener called. password=True, cert=True, ca=True, peers=1
[S2S] S2S UDP listener started on port 6667
S2S role: leaf
[S2S] S2S peer linker started, will try to link to 1 peer(s)
```

---

## Code Changes Summary

| File | Method | Change | Lines |
|------|--------|--------|-------|
| server_network.py | `_load_cert_config()` | Add role loading | +1 |
| server_network.py | `_load_cert_config()` | Add role logging | +1 |
| server_network.py | `start_listener()` | Conditional peer linker | +2 |
| server_network.py | `_start_peer_linker()` | Early return for hub | +2 |
| **Total** | | | **+6 lines** |

---

## Backward Compatibility

✅ **Fully backward compatible**

- Default role: `'leaf'` (maintains current behavior)
- Missing config key: Defaults to `'leaf'`
- Existing deployments: No changes needed
- Hub behavior: Only when explicitly configured

---

## Rollback Plan

If issues arise:

1. Remove `s2s_role` key from csc-service.json (reverts to 'leaf')
2. Remove role checks from code (revert to current behavior)
3. All servers behave as current leaf (backward compatible)

---

## Environment Variables (Future Enhancement)

Could also support:
```python
self.s2s_role = os.environ.get('CSC_S2S_ROLE', cfg.get("s2s_role", "leaf"))
```

This would allow override at runtime without config file change.

---

## Related Files

- **Config file:** `$CSC_HOME/csc-service.json`
- **Server class:** Assumes `self._log()` method exists
- **Peer linking:** Handled by `_start_peer_linker()` and `_peer_link_loop()`
- **Listener:** Handled by `_receive_loop()`

---

## Questions & Answers

**Q: What if only `start_listener()` check is needed?**
A: Both checks are needed for defense-in-depth:
   - `start_listener()` stops normal execution
   - `_start_peer_linker()` catches any direct calls

**Q: What if role is misspelled (e.g., "Hub" instead of "hub")?**
A: Won't match 'hub', so behaves as 'leaf'. Safe default.

**Q: Can role be changed at runtime?**
A: Not with current implementation. Would need additional code to support.

**Q: Should leaf servers ignore configured peers if none exist?**
A: Yes, handled by existing check: `if not self.s2s_peers: return`

---

## Debugging

Add these logging statements if needed:

```python
# In _load_cert_config()
dlog("CONFIG", f"Loaded s2s_role={self.s2s_role}")

# In start_listener()
print(f"[S2S] s2s_role={self.s2s_role}, will start peer linker: {self.s2s_role == 'leaf'}")

# In _start_peer_linker()
dlog("PEER", f"_start_peer_linker called, role={self.s2s_role}")
```

---
