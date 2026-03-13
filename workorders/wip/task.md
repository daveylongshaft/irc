# Benchmark Diagnosis: Channel Name Case Normalization Issue

## Test Failure
**Test**: `tests/test_server_irc.py::test_privmsg_to_channel`

**Error Message**:
```
AssertionError: Expected message to contain 'PRIVMSG #general :hello'
but got 'PRIVMSG #General :hello'
```

**Root Cause**: The server is not normalizing channel names to lowercase before routing PRIVMSG messages. This causes the protocol output to preserve the case from the client's input instead of normalizing to the standard lowercase format.

---

## Root Cause Analysis

### Issue Location
**File**: `packages/csc-service/csc_service/server/server_message_handler.py`  
**Function**: `_handle_privmsg()` (lines 690-763)  
**Specific Problem**: Line 727

### The Problem
In the `_handle_privmsg()` method, when a PRIVMSG is sent to a channel, the handler constructs the output message using the channel target name as provided by the client:

```python
# Line 700
target = msg.params[0]
# Line 727
out = format_irc_message(prefix, "PRIVMSG", [target], text) + "\r\n"
```

The `target` variable contains the channel name exactly as sent by the client (e.g., "#General", "#GENERAL", "#general"), and this is directly passed to `format_irc_message()` without normalization.

### Channel Lookup Works Correctly
Interestingly, the channel **lookup** itself works correctly because the `ChannelManager.get_channel()` method (line 616 in `channel.py`) normalizes the lookup key to lowercase:

```python
# From channel.py line 616
def get_channel(self, name: str) -> Optional[Channel]:
    return self.channels.get(name.lower())
```

So if a client sends `PRIVMSG #General :hello`, the server:
1. ✅ **Correctly finds** the channel by normalizing "#General" to "#general"
2. ✅ **Correctly broadcasts** to all channel members
3. ❌ **Incorrectly broadcasts** with the non-normalized channel name in the output

---

## Expected vs. Actual Behavior

### Expected (IRC Standard)
- Client sends: `PRIVMSG #General :hello`
- Server broadcasts: `PRIVMSG #general :hello` (normalized to lowercase)

### Actual (Current Bug)
- Client sends: `PRIVMSG #General :hello`
- Server broadcasts: `PRIVMSG #General :hello` (preserves client's casing)

### Why This Matters
RFC 1459 (IRC Protocol) defines channel names as case-insensitive, and best practice is to normalize them to lowercase in protocol output for consistency. This affects:
- Client display consistency
- Log analysis and scripts that expect lowercase channels
- Cross-server federation compatibility

---

## Proposed Fix

### Location
**File**: `packages/csc-service/csc_service/server/server_message_handler.py`  
**Function**: `_handle_privmsg()`  
**Lines**: 705-730

### Solution
Normalize the channel name to lowercase when constructing the IRC message output for channel PRIVMSG. The fix would be implemented as:

```python
def _handle_privmsg(self, msg, addr):
    """PRIVMSG <target> :<text>"""
    nick = self._get_nick(addr)
    if len(msg.params) < 1:
        self._send_numeric(addr, ERR_NORECIPIENT, nick, "No recipient given (PRIVMSG)")
        return
    if len(msg.params) < 2:
        self._send_numeric(addr, ERR_NOTEXTTOSEND, nick, "No text to send")
        return

    target = msg.params[0]
    text = msg.params[-1]  # trailing text

    prefix = f"{nick}!{nick}@{SERVER_NAME}"

    if target.startswith("#"):
        # Channel message
        channel = self.server.channel_manager.get_channel(target)
        if not channel:
            self._send_numeric(addr, ERR_NOSUCHCHANNEL, nick,
                               f"{target} :No such channel")
            return
        if not channel.has_member(nick):
            self._send_numeric(addr, ERR_CANNOTSENDTOCHAN, nick,
                               f"{target} :Cannot send to channel")
            return
        # ... permission checks ...
        
        # FIX: Normalize the channel name for output
        normalized_target = target.lower()  # NEW LINE
        out = format_irc_message(prefix, "PRIVMSG", [normalized_target], text) + "\r\n"  # MODIFIED
        
        # Broadcast using normalized channel name
        self._broadcast_privmsg_filtered(channel, out, text, nick, exclude=addr)
        
        # Also normalize when appending to chat buffer
        self.server.chat_buffer.append(normalized_target, nick, "PRIVMSG", text)  # MODIFIED
        # ... rest of function ...
```

### Key Changes
1. **Line 727** (new): Add `normalized_target = target.lower()`
2. **Line 728** (modified): Use `normalized_target` instead of `target` in `format_irc_message()`
3. **Line 730** (modified): Use `normalized_target` instead of `target` in `chat_buffer.append()`

### Rationale
- **Minimal change**: Only affects the output formatting, not the lookup logic
- **Consistent**: Aligns with RFC 1459 and common IRC server behavior
- **Preserves functionality**: All existing channel lookups and member operations continue to work correctly
- **Backward compatible**: Clients that send lowercase channel names are unaffected; those that send mixed/uppercase will now see normalized output

---

## Scope of Issue

This same normalization pattern should be checked in other PRIVMSG-related functions:
- `_handle_notice()` (line 922) - similar issue likely exists
- `_broadcast_privmsg_filtered()` (line 847) - receives channel object, not channel name, so likely OK
- Any other place where protocol messages are formatted with channel targets

---

## Testing Validation

The fix would be validated by:
1. Running the failing test with uppercase channel: `PRIVMSG #General :hello`
2. Verifying broadcast output normalizes to: `PRIVMSG #general :hello`
3. Confirming all channel members still receive the message
4. Running the full test suite to ensure no regressions
START
implementing privmsg normalization fix
checking for similar issues in _handle_notice
writing test for channel normalization
COMPLETE
deleting stale test log
running refresh-maps
START
reading packages/csc-service/csc_service/server/server_message_handler.py to understand the code
implementing privmsg and notice normalization fix
checking for similar issues in _handle_notice
writing test for channel normalization
COMPLETE
running refresh-maps
deleting stale test log
START 2026-03-12 21:01:03 PID:42088
Reading server_message_handler.py to find the _handle_privmsg function
Implementing channel name normalization in _handle_privmsg
Implementing channel name normalization in _handle_notice
Writing test for channel name case normalization
Verifying the changes are correct
Deleting stale test log to trigger retest
COMPLETE
Verification: All changes committed and complete

## Verification Summary 2026-03-12 21:17:49

Agent: sonnet (current session)
Status: VERIFIED COMPLETE

### Changes Confirmed:
1. ✓ packages/csc-service/csc_service/server/server_message_handler.py
   - Line 738-740: _handle_privmsg() normalizes channel names to lowercase
   - Line 956-958: _handle_notice() normalizes channel names to lowercase
   
2. ✓ tests/test_channel_normalization.py
   - test_privmsg_channel_name_normalization
   - test_notice_channel_name_normalization
   - test_privmsg_already_lowercase_unchanged
   - test_privmsg_uppercase_channel_normalized

3. ✓ Git Status: All changes committed (f05fb42)
   - Working tree clean
   - No uncommitted changes

### Implementation Details:
- Added `normalized_target = target.lower()` before formatting IRC messages
- Applied to both PRIVMSG and NOTICE handlers
- Consistent with RFC 1459 (case-insensitive channels)
- All chat_buffer.append() calls use normalized names

COMPLETE
