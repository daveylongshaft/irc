# S2S Role Gating Implementation Checklist

## Pre-Implementation Review

- [ ] Review current code at lines 793-830 (_load_cert_config)
- [ ] Review current code at lines 849-873 (start_listener)
- [ ] Review current code at lines 875-881 (_start_peer_linker)
- [ ] Verify no other code directly calls _start_peer_linker besides start_listener
- [ ] Check for any hardcoded assumptions about peer linking

---

## Implementation Steps

### Step 1: Add s2s_role initialization in __init__

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

- [ ] Locate line 777: `self.s2s_peers = []`
- [ ] Add blank line after 777
- [ ] Add comment: `# S2S role: 'hub' (accepts inbound only) or 'leaf' (initiates outbound only)`
- [ ] Add assignment: `self.s2s_role = 'leaf'    # Default to leaf role`
- [ ] Verify indentation matches surrounding code (8 spaces)
- [ ] Save file

**Verify:** Run `grep -n "self.s2s_role = 'leaf'" packages/csc-server-core/csc_server_core/server_network.py`
- Should show line ~780

---

### Step 2: Load s2s_role from config in _load_cert_config()

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

- [ ] Locate line 814: `self.s2s_peers = cfg.get("s2s_peers", [])`
- [ ] Add new line after 814
- [ ] Type: `self.s2s_role = cfg.get("s2s_role", "leaf")  # Default to 'leaf'`
- [ ] Verify indentation matches surrounding code (12 spaces for inside try block)
- [ ] Save file

**Verify:** Run `grep -n "cfg.get.*s2s_role" packages/csc-server-core/csc_server_core/server_network.py`
- Should show the new line

---

### Step 3: Conditionally call _start_peer_linker in start_listener()

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

- [ ] Locate line 869: `self._log(f"S2S UDP listener started on port {self.s2s_port}")`
- [ ] Locate line 870: `self._start_peer_linker()`
- [ ] Replace line 870 with TWO lines:
  - Line 870: `if self.s2s_role == 'leaf':`
  - Line 871: `    self._start_peer_linker()`  (indented 4 more spaces)
- [ ] Verify indentation: `if` at 12 spaces, method call at 16 spaces
- [ ] Line 872 should now be: `return True`
- [ ] Save file

**Verify:** Run `sed -n '869,872p' packages/csc-server-core/csc_server_core/server_network.py`
- Should show:
  ```
  self._log(f"S2S UDP listener started on port {self.s2s_port}")
  if self.s2s_role == 'leaf':
      self._start_peer_linker()
  return True
  ```

---

### Step 4: Add early return in _start_peer_linker() for hub role

**File:** `packages/csc-server-core/csc_server_core/server_network.py`

- [ ] Locate line 876: `"""Start a thread that periodically tries to link to configured S2S peers."""`
- [ ] After line 876, insert 3 new lines:
  - Line 877: `# Hub role does not initiate outbound connections`
  - Line 878: `if self.s2s_role == 'hub':`
  - Line 879: `    return`
- [ ] Existing `if not self.s2s_peers:` check becomes line 880
- [ ] Verify indentation: comment at 8 spaces, if at 8 spaces, return at 12 spaces
- [ ] Save file

**Verify:** Run `sed -n '875,882p' packages/csc-server-core/csc_server_core/server_network.py`
- Should show:
  ```
  def _start_peer_linker(self):
      """Start a thread that periodically tries to link to configured S2S peers."""
      # Hub role does not initiate outbound connections
      if self.s2s_role == 'hub':
          return
      if not self.s2s_peers:
          return
      self._peer_link_thread = threading.Thread(target=self._peer_link_loop, daemon=True)
  ```

---

## Code Review Checklist

After all 4 changes:

- [ ] All indentation is consistent (spaces, not tabs)
- [ ] No syntax errors: `python -m py_compile packages/csc-server-core/csc_server_core/server_network.py`
- [ ] All method signatures unchanged
- [ ] All docstrings unchanged
- [ ] Comments are clear and accurate
- [ ] No lines exceed 100 characters (if project standard)

---

## Functional Testing Checklist

### Test 1: Default Behavior (No s2s_role in config)
- [ ] Create test instance WITHOUT `s2s_role` in csc-service.json
- [ ] Verify `s2s_role` defaults to `'leaf'`
- [ ] Verify listener starts
- [ ] Verify peer linker thread starts
- [ ] Verify backward compatibility

### Test 2: Explicit Hub Role
- [ ] Create test instance with `"s2s_role": "hub"` in csc-service.json
- [ ] Verify `s2s_role` is `'hub'`
- [ ] Verify listener starts
- [ ] Verify peer linker thread does NOT start
- [ ] Check logs for no peer linker messages

### Test 3: Explicit Leaf Role
- [ ] Create test instance with `"s2s_role": "leaf"` in csc-service.json
- [ ] Verify `s2s_role` is `'leaf'`
- [ ] Verify listener starts
- [ ] Verify peer linker thread starts
- [ ] Check logs for peer linker startup message

### Test 4: No S2S Config
- [ ] Create test instance with no S2S config
- [ ] Verify listener does NOT start
- [ ] Verify peer linker does NOT start
- [ ] No errors in logs

### Test 5: Hub with Peers (Edge Case)
- [ ] Create hub instance with `"s2s_peers": [...]`
- [ ] Verify listener starts
- [ ] Verify peer linker does NOT start (despite having peers)
- [ ] Verify no errors

---

## Logging Verification

Add these checks to logs:

- [ ] Hub instance startup: Should see "S2S UDP listener started on port 9520"
- [ ] Hub instance startup: Should NOT see "S2S peer linker started"
- [ ] Leaf instance startup: Should see "S2S UDP listener started on port 9520"
- [ ] Leaf instance startup: Should see "S2S peer linker started, will try to link to X peer(s)"
- [ ] Config loading: s2s_role value should be logged (optional, debug level)

---

## Integration Testing

- [ ] Deploy hub instance and leaf instance
- [ ] Hub: Verify it accepts inbound connections from leaf
- [ ] Leaf: Verify it connects to hub
- [ ] Verify S2S message flow works in both directions
- [ ] Verify no loop prevention issues
- [ ] Run full S2S integration test suite

---

## Documentation Updates Needed

- [ ] Update csc-service.json schema documentation
- [ ] Document `s2s_role` option (hub vs leaf)
- [ ] Document default behavior
- [ ] Document configuration examples
- [ ] Update S2S deployment guide
- [ ] Update troubleshooting guide

---

## Rollback Plan

If issues arise:

1. Revert the 4 changes above
2. Restart services
3. Verify backward compatibility (should default to leaf)

---

## Sign-Off

- [ ] Code changes reviewed
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Documentation updated
- [ ] Ready for merge

---

## Implementation Notes

**Key Implementation Details:**

1. **Default Value:** Always default to `'leaf'` for backward compatibility
2. **Loading Order:** 
   - __init__ sets default to 'leaf'
   - _load_cert_config() may override from JSON
   - Value available when start_listener() is called
3. **Double Protection:** 
   - Check in start_listener() (caller)
   - Check in _start_peer_linker() (callee)
4. **No Race Conditions:** s2s_role loaded before start_listener() called
5. **No Performance Impact:** Simple string comparison checks

**Testing Shortcuts:**

```bash
# Quick syntax check
python -m py_compile packages/csc-server-core/csc_server_core/server_network.py

# Search for all instances
grep -n "s2s_role" packages/csc-server-core/csc_server_core/server_network.py

# View the 4 change locations
sed -n '778,782p' packages/csc-server-core/csc_server_core/server_network.py
sed -n '814,816p' packages/csc-server-core/csc_server_core/server_network.py
sed -n '869,872p' packages/csc-server-core/csc_server_core/server_network.py
sed -n '875,882p' packages/csc-server-core/csc_server_core/server_network.py
```
