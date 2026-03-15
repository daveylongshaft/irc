# Shared File Divergence Audit

**Date:** 2026-02-14
**Task:** 50 - Audit & Reconcile Shared File Divergence
**Status:** Audit complete (read-only, no files modified)

---

## Summary

| File | Status | Action Needed |
|------|--------|---------------|
| data.py | Identical everywhere | Delete app copies |
| log.py | Identical everywhere | Delete app copies |
| root.py | Identical everywhere | Delete app copies |
| crypto.py | Identical (server, translator) | Delete app copies |
| channel.py | Identical (server = shared) | Delete server copy |
| chat_buffer.py | Only in shared/ | None |
| irc.py | **Diverged** - apps missing 45 lines | Sync apps to shared |
| network.py | **Diverged** - apps have race condition bug | Sync apps to shared |
| version.py | **Diverged** - apps missing workflow notify | Sync apps to shared |
| secret.py | **Severely diverged** - needs restructuring | See detailed plan |

---

## 1. Confirmed Identical Files

These files are byte-identical across all locations. The app copies can be safely deleted and replaced with imports from shared/.

### data.py
- **Locations:** shared/, server/, client/, gemini/, translator/
- **Verdict:** All identical. shared/ is canonical.

### log.py
- **Locations:** shared/, server/, client/, gemini/, translator/
- **Verdict:** All identical. shared/ is canonical.

### root.py
- **Locations:** shared/, server/, client/, gemini/, translator/
- **Verdict:** All identical. shared/ is canonical.

### crypto.py
- **Locations:** shared/, server/, translator/
- **Verdict:** All identical. shared/ is canonical.

### channel.py
- **Locations:** shared/ (156 lines), server/ (156 lines)
- **Verdict:** Identical. shared/ is canonical.

### chat_buffer.py
- **Locations:** shared/ only
- **Verdict:** No duplication. Already unique to shared/.

---

## 2. Diverged Files - Detailed Analysis

### irc.py

**Locations:** shared/ (223 lines), client/ (178 lines), gemini/ (178 lines), translator/ (178 lines)

**What shared/ has that apps don't (45 lines):**
- WHOIS response codes: RPL_WHOISUSER (311), RPL_WHOISSERVER (312), RPL_WHOISOPERATOR (313), RPL_ENDOFWHOIS (318)
- WHOWAS response codes: RPL_WHOWASUSER (314), RPL_ENDOFWHOWAS (369), ERR_WASNOSUCHNICK (406)
- User mode codes: RPL_UMODEIS (221)
- Away codes: RPL_AWAY (301), RPL_UNAWAY (305), RPL_NOWAWAY (306)
- ERR_NOPRIVILEGES (481)
- User mode errors: ERR_UMODEUNKNOWNFLAG (501), ERR_USERSDONTMATCH (502)
- Channel errors: ERR_CHANNELISFULL (471), ERR_UNKNOWNMODE (472), ERR_INVITEONLYCHAN (473), ERR_BADCHANNELKEY (475)
- INVITE: RPL_INVITING (341)
- WHOIS channels: RPL_WHOISCHANNELS (319)
- Ban list: RPL_BANLIST (367), RPL_ENDOFBANLIST (368), ERR_BANNEDFROMCHAN (474), ERR_BANLISTFULL (478)

**Canonical version:** shared/ (most complete)

**Reconciliation plan:**
- Replace client/irc.py, gemini/irc.py, translator/irc.py with shared/ version
- These are pure constant definitions with no app-specific logic

---

### network.py

**Locations:** shared/ (195 lines), server/ (194 lines), client/ (190 lines), gemini/ (190 lines), translator/ (190 lines)

**Critical bug in app versions (client, gemini, translator):**
The `_listener` method has a race condition. When updating `last_seen` for a client address, the app versions overwrite the entire dict entry:
```python
# BROKEN (client/gemini/translator) - loses 'name' and other fields:
self.clients[addr] = {"last_seen": time.time()}
```

The shared/ version preserves existing fields:
```python
# FIXED (shared/) - preserves 'name' and other fields:
if addr not in self.clients:
    self.clients[addr] = {"last_seen": time.time()}
else:
    self.clients[addr]["last_seen"] = time.time()
```

**server/ vs shared/:** Only a comment wording difference (same logic). Functionally identical.

**Canonical version:** shared/ (has the race condition fix + best comments)

**Reconciliation plan:**
- Replace all app copies with shared/ version
- Server copy comment difference is cosmetic only

---

### version.py

**Locations:** shared/ (252 lines), server/ (243 lines), client/ (243 lines), gemini/ (243 lines), translator/ (243 lines)

**What shared/ has that apps don't (9 lines):**
After creating a file version, shared/ notifies the prompts service:
```python
# Notify Prompts service if active
try:
    if hasattr(self, "server") and hasattr(self.server, "loaded_modules"):
        prompts = self.server.loaded_modules.get("prompts")
        if prompts:
            prompts.version_file(filepath)
except Exception as e:
    self.log(f"Warning: Failed to notify prompts service: {e}")
```

**Note:** This code references `self.server.loaded_modules` which is server-specific. On non-server apps, `hasattr(self, "server")` will be False and the block is safely skipped. It's harmless in all contexts.

**Canonical version:** shared/ (superset, safe for all apps)

**Reconciliation plan:**
- Replace all app copies with shared/ version
- The prompts notification is server-only but safely no-ops elsewhere

---

### secret.py - SEVERELY DIVERGED

**Locations and sizes:**
- shared/ (357 lines) - Clean, comprehensive
- server/ - Symlink to shared/secret.py (already correct)
- client/ (92 lines) - Stripped down, missing functions
- gemini/ (205 lines) - Heavily modified system instructions

#### shared/secret.py (canonical) contains:
1. Path setup boilerplate (lines 1-24)
2. `get_gemini_api_key()` - returns hardcoded Gemini API key
3. `get_claude_api_key()` - reads from ANTHROPIC_API_KEY env var
4. `get_gemini_oper_credentials()` - returns ("Gemini", "gemini_oper_key")
5. `get_claude_oper_credentials()` - returns ("Claude", "claude_oper_key")
6. `get_known_core_files()` - list of core filenames
7. `load_initial_core_file_context()` - reads core files for AI context
8. `get_system_instructions()` - Gemini system prompt (250+ lines)

#### client/secret.py is MISSING:
- `get_gemini_oper_credentials()`
- `get_claude_oper_credentials()`
- `get_system_instructions()` (entire function)

The client doesn't call these functions, so it works fine without them.

#### gemini/secret.py has MODIFIED system instructions:
The `get_system_instructions()` function differs substantially from shared/:
- Missing: `get_gemini_oper_credentials()` and `get_claude_oper_credentials()`
- Removed: todolist and workflow service references from AVAILABLE SERVICES
- Removed: CONNECTION CONTROL COMMANDS section
- Removed: detailed workflow collaboration steps
- Modified: EXPLORATION DIRECTIVE simplified (removed todolist/workflow checks)
- Modified: AUTONOMOUS HEARTBEAT simplified
- Modified: COLLABORATION & MODULE APPROVAL (truncated)
- Added: hardcoded credentials and alternate directives at top of instructions
- Added: ntfy.sh notification directive
- Added: alternate MISSION STATEMENT at bottom

#### Reconciliation analysis:

**What belongs in shared/ (common to all apps):**
- Path setup boilerplate
- `get_gemini_api_key()`
- `get_claude_api_key()`
- `get_gemini_oper_credentials()`
- `get_claude_oper_credentials()`
- `get_known_core_files()`
- `load_initial_core_file_context()`

**What is app-specific (should NOT be in shared/):**
- `get_system_instructions()` is exclusively used by the Gemini client. It should live in gemini/ and import common functions from shared.

**Reconciliation plan:**
1. shared/secret.py: Remove `get_system_instructions()` (Gemini-specific)
2. gemini/secret.py: Keep only `get_system_instructions()`, import everything else from shared
3. client/secret.py: Delete entirely, have client import from shared
4. server/secret.py: Remains symlink to shared/ (already correct)
5. shared/ version's system instructions content is canonical (comprehensive collaboration/workflow/versioning)

---

## 3. Reconciliation Plan - Execution Order

### Phase 1: Drop-in replacements (no code changes needed)
These are pure constants or have safe superset logic. Replace app copies with shared/:
- irc.py -> client/, gemini/, translator/
- network.py -> server/, client/, gemini/, translator/ (fixes race condition bug!)
- version.py -> server/, client/, gemini/, translator/

### Phase 2: Restructure secret.py
1. Move `get_system_instructions()` out of shared/secret.py into gemini/secret.py
2. Update gemini/secret.py to import common functions from shared
3. Delete client/secret.py, have client import from shared
4. Operator review needed: decide which version of system instructions is authoritative

### Phase 3: Delete confirmed-identical app copies
Once apps import from shared/, delete these duplicates:
- data.py from server/, client/, gemini/, translator/
- log.py from server/, client/, gemini/, translator/
- root.py from server/, client/, gemini/, translator/
- crypto.py from server/, translator/
- channel.py from server/

### Notes
- server/secret.py symlink pattern is good; package imports (task 51) will replace all symlinks
- claude/ and chatgpt/ use a different architecture (no shared file copies) - not affected
- The network.py race condition fix is the highest-priority sync (active bug in 3 apps)

## Phase 2: Secret.py Restructuring - COMPLETE

Date: 2026-02-14

### What was done:
1. **shared/secret.py**: Reduced from 357 lines to 105 lines
   - Removed get_system_instructions() function (Gemini-specific)
   - Kept only common functions: get_gemini_api_key(), get_claude_api_key(), 
     get_gemini_oper_credentials(), get_claude_oper_credentials(), 
     get_known_core_files(), load_initial_core_file_context()

2. **gemini/secret.py**: Restructured
   - Now imports common functions from shared.secret
   - Defines only get_system_instructions() (Gemini-specific)
   - 288 lines (full instructions preserved)

3. **client/secret.py**: Deleted
   - Client will now import from shared/secret.py (common functions only)
   - Client doesn't need get_system_instructions() or operator credentials

4. **server/secret.py**: Unchanged
   - Remains a symlink to shared/secret.py (correct)

### Verification:
- ✓ All imports working (tested with Python)
- ✓ Gemini can call get_system_instructions() from its own module
- ✓ Gemini imports common functions from shared
- ✓ Secret files correctly ignored in .gitignore (contain API keys)
